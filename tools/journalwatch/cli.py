# -*- coding: utf-8 -*-
"""盯新刊的命令行入口：列出好期刊最近新登记的论文，标出库里有没有。

用法:
  python -m tools.journalwatch                 最近 7 天，所有盯着的刊
  python -m tools.journalwatch --天 3          只看最近 3 天
  python -m tools.journalwatch --只看新的      只列这次首见的（定时跑用这个）
  python -m tools.journalwatch --过线          只列过了相关度门槛的（引了库内 A≥2 / B≥1 / C≥3 篇）
  python -m tools.journalwatch --刊 Macro      只看名字里带 Macro 的刊
  python -m tools.journalwatch --含摘要        每篇带一行摘要
  python -m tools.journalwatch --不记          只看看，不把这些记成「见过」、不入雷达库
  python -m tools.journalwatch --回填 3        把过去 3 年的都拉进雷达库（跑一晚上；断了再跑接着来）
  python -m tools.journalwatch --雷达          雷达库现在有多少：篇数 / 带摘要 / 库里有 / 引用边
  python -m tools.journalwatch --补摘要 400    用 OpenAlex 给没摘要的补（一批 50 篇，400 批约 $0.04）

盯哪些刊：改 data/serving/journal_watch.json（name + ISSN；不想盯的加 "off": true）。
看完想收哪几篇：python -m tools.discover.collect 1,3,5-7（编号就是本次列表的编号）。

不花钱、不写 Zotero、不取全文 —— 只问 Crossref 登记处。
"""
import io
import json
import os
import sys
import time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import paths
from shared.kernel.cli import flag, opt, wants_help
from tools import journalwatch


def _stash(rows):
    """存成和「找新文献」同一种暂存格式，`tools.discover.collect` 就能按编号收。"""
    try:
        io.open(paths.last_search(), 'w', encoding='utf-8').write(json.dumps(
            {'query': '盯新刊', 'time': time.strftime('%Y-%m-%d %H:%M'),
             'items': [{'n': i, 'title': w['title'], 'doi': w['doi'], 'year': w.get('year'),
                        'citations': w.get('citations', 0), 'relevance': None,
                        'status': '库里有' if w['in_library'] else '新'}
                       for i, w in enumerate(rows, 1)]},
            ensure_ascii=False, indent=1))
    except Exception:
        pass


def _radar_stats():
    con = journalwatch.store.connect()
    try:
        st = journalwatch.store.stats(con)
    finally:
        con.close()
    print('雷达库：%d 篇，带摘要 %d，证据库里已有 %d，引用边 %d 条，出版日 %s ~ %s' % (
        st['works'], st['with_abstract'], st['in_library'], st['refs'], st['span'][0], st['span'][1]))
    for v, n in st['by_venue'][:40]:
        print('  %6d  %s' % (n, v))
    return 0


def _backfill(years, pick):
    journals = journalwatch.load_journals()
    if pick:
        journals = [j for j in journals if pick in j['name'].lower()]
    print('回填 %d 本刊、最近 %d 年 ……（每块做完即入库，中断了再跑会接着）' % (len(journals), years))
    r = journalwatch.backfill(years=years, journals=journals, log=print)
    print('\n新增 %d 篇，做了 %d 块%s' % (r['works'], r['chunks'],
                                      ('；没拉完的刊：' + '、'.join(r['failed'])) if r['failed'] else ''))
    return 0


def main():
    if wants_help():
        print(__doc__)
        return 0
    if flag('--雷达'):
        return _radar_stats()
    if opt('--补摘要'):
        f, n = journalwatch.fill_abstracts(int(opt('--补摘要') or 400), log=print)
        print('补上 %d / 问了 %d' % (f, n))
        return 0
    if opt('--回填'):
        return _backfill(int(opt('--回填') or 3), (opt('--刊') or '').strip().lower())
    days = int(opt('--天', 7) or 7)
    only_new = flag('--只看新的')
    pick = (opt('--刊') or '').strip().lower()
    with_abs = flag('--含摘要')
    journals = journalwatch.load_journals()
    if pick:
        journals = [j for j in journals if pick in j['name'].lower()]
        if not journals:
            print('清单里没有名字带「%s」的刊。清单在：%s' % (pick, paths.journal_watch()))
            return 1
    print('盯 %d 本刊，最近 %d 天 ……' % (len(journals), days))
    r = journalwatch.patrol(days=days, journals=journals, log=print, only_new=only_new,
                            remember=not flag('--不记'))
    rows = r['items']
    if r['failed']:
        print('\n没查成的刊（下次再试）：' + '、'.join(r['failed']))
    if not rows:
        print('\n这段时间没有新文章%s。' % ('（或都见过了）' if only_new else ''))
        return 0
    n_new = sum(1 for w in rows if w['is_new'])
    n_have = sum(1 for w in rows if w['in_library'])
    n_pass = sum(1 for w in rows if w.get('passes'))
    print('\n共 %d 篇（首见 %d，库里已有 %d，**过线 %d**）：' % (len(rows), n_new, n_have, n_pass))
    if flag('--过线'):
        rows = [w for w in rows if w.get('passes')]
        rows.sort(key=lambda w: (-w['lib_cites'], w['venue']))
    cur = None
    for i, w in enumerate(rows, 1):
        if w['venue'] != cur:
            cur = w['venue']
            print('\n── %s（%s 档）' % (cur, w.get('tier', '?')))
        mark = '库' if w['in_library'] else ('新' if w['is_new'] else '  ')
        cites = ('引%d篇%s' % (w['lib_cites'], '✓' if w.get('passes') else '')) if w.get('lib_cites') else ''
        print('%3d. [%s] %s  %s  %s' % (i, mark, w['published'] or w['created'], w['title'][:96], cites))
        print('        %s' % w['doi'])
        if with_abs and w.get('abstract'):
            print('        ' + w['abstract'][:220].replace('\n', ' '))
    _stash(rows)
    print('\n想收哪几篇：python -m tools.discover.collect 1,3,5-7')
    return 0


if __name__ == '__main__':
    sys.exit(main())
