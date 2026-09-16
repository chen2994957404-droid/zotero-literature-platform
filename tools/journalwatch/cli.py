# -*- coding: utf-8 -*-
"""盯新刊的命令行入口：列出好期刊最近新登记的论文，标出库里有没有。

用法:
  python -m tools.journalwatch                 最近 7 天，所有盯着的刊
  python -m tools.journalwatch --天 3          只看最近 3 天
  python -m tools.journalwatch --只看新的      只列这次首见的（定时跑用这个）
  python -m tools.journalwatch --刊 Macro      只看名字里带 Macro 的刊
  python -m tools.journalwatch --含摘要        每篇带一行摘要
  python -m tools.journalwatch --不记          只看看，不把这些记成「见过」

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


def main():
    if wants_help():
        print(__doc__)
        return 0
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
    print('\n共 %d 篇（首见 %d 篇，库里已有 %d 篇）：' % (len(rows), n_new, n_have))
    cur = None
    for i, w in enumerate(rows, 1):
        if w['venue'] != cur:
            cur = w['venue']
            print('\n── %s' % cur)
        mark = '库' if w['in_library'] else ('新' if w['is_new'] else '  ')
        print('%3d. [%s] %s  %s' % (i, mark, w['published'] or w['created'], w['title'][:100]))
        print('        %s' % w['doi'])
        if with_abs and w.get('abstract'):
            print('        ' + w['abstract'][:220].replace('\n', ' '))
    _stash(rows)
    print('\n想收哪几篇：python -m tools.discover.collect 1,3,5-7')
    return 0


if __name__ == '__main__':
    sys.exit(main())
