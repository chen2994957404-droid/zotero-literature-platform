# -*- coding: utf-8 -*-
"""盘点：库里到底有什么 —— 按类型（论文 / 学位论文 / 专利 / 其他）、按手上有什么（正文 / SI / 精读）。

用户 2026-09-17 问：「库里有毕业论文、专利、有 SI 的、没加 SI 的、本来就没 SI 的，有统计吗」—— 以前没有。
两边各数一遍再对上：
  Zotero（他自己挑出来读的子集）：按 itemType 分类；每条有没有正文 PDF、有没有 SI 附件、有没有 DOI
  证据库（全集，零网络）：有正文原件 / 解析过 / SI 三态（有 / 出版商确认没有 / 没取过）/ 精读 / 结构化
**只读**。Zotero 没开就只出证据库那一半。

用法：python -m tools.library 盘点 [--明细]
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from collections import Counter, defaultdict

from shared.adapters import zotero_client as zc
from shared.kernel import catalog, paths

# Zotero 的 itemType → 给人看的类
KIND = {'journalArticle': '期刊论文', 'preprint': '预印本', 'conferencePaper': '会议论文',
        'thesis': '学位论文', 'patent': '专利', 'book': '书', 'bookSection': '书的章节',
        'report': '报告', 'webpage': '网页', 'document': '文档'}


def _zotero_side():
    """Zotero 顶层条目逐条：{key, kind, title, doi, pdf, si}。没开 → None。"""
    if not zc.alive():
        return None
    uid = zc._local_uid()
    # 一次把全部附件拉下来按父条目分组，比逐条问 children 少几百次请求
    atts = defaultdict(list)
    start = 0
    while True:
        d = zc.zget(f'/users/{uid}/items?itemType=attachment&limit=100&start={start}')
        if not d:
            break
        for a in d:
            ad = a['data']
            if ad.get('parentItem'):
                atts[ad['parentItem']].append(ad)
        start += 100
    rows = []
    start = 0
    while True:
        d = zc.zget(f'/users/{uid}/items/top?limit=100&start={start}')
        if not d:
            break
        for x in d:
            xd = x['data']
            if xd.get('itemType') in ('attachment', 'note', 'annotation'):
                continue
            pdf = si = False
            for ad in atts.get(xd['key'], []):
                if ad.get('contentType') not in ('application/pdf', zc.DOCX_CT):
                    continue
                title = (ad.get('title') or '').strip()
                fn = ad.get('filename') or ''
                if zc.SUPP_PAT.search(title) or zc.SUPP_PAT.search(fn) or title.upper() == 'SI':
                    si = True
                elif ad.get('contentType') == 'application/pdf':
                    pdf = True
            rows.append({'key': xd['key'], 'kind': KIND.get(xd.get('itemType'), xd.get('itemType') or '?'),
                         'title': (xd.get('title') or '')[:60], 'doi': catalog.norm_doi(xd.get('DOI') or ''),
                         'pdf': pdf, 'si': si})
        start += 100
    return rows


def _evidence_side():
    """证据库逐篇：目录卡 + SI 三态。"""
    rows = []
    for pid in catalog.ids():
        r = catalog.record(pid)
        r['si_status'] = catalog.si_status(pid)
        rows.append(r)
    return rows


def census():
    """→ dict：两边的汇总 + 明细行。"""
    ev = _evidence_side()
    zt = _zotero_side()
    ev_doi = {r['doi'] for r in ev if r['doi']}
    out = {'evidence': {'total': len(ev),
                        'pdf': sum(r['pdf'] for r in ev),
                        'fulltext': sum(r['fulltext'] for r in ev),
                        'summary': sum(r['summary'] for r in ev),
                        'structured': sum(r['structured'] for r in ev),
                        'no_doi': sum(1 for r in ev if not r['doi']),
                        'si': Counter(r['si_status'] for r in ev if r['pdf']),
                        'in_zotero': sum(r['in_zotero'] for r in ev)},
           'zotero': None, 'rows_evidence': ev, 'rows_zotero': zt}
    if zt is not None:
        kinds = Counter(r['kind'] for r in zt)
        art = [r for r in zt if r['kind'] in ('期刊论文', '预印本', '会议论文')]
        out['zotero'] = {'total': len(zt), 'kinds': kinds,
                         'no_doi': sum(1 for r in zt if not r['doi']),
                         'no_pdf': sum(1 for r in zt if not r['pdf'] and not r['si']),
                         'articles': len(art),
                         'art_pdf_si': sum(1 for r in art if r['pdf'] and r['si']),
                         'art_pdf_only': sum(1 for r in art if r['pdf'] and not r['si']),
                         'art_no_pdf': sum(1 for r in art if not r['pdf']),
                         'not_in_evidence': sum(1 for r in zt if r['doi'] and r['doi'] not in ev_doi),
                         # 只有正文、没 SI 附件的论文里，证据库怎么说它的 SI
                         'art_pdf_only_si': Counter(
                             next((e['si_status'] for e in ev if e['doi'] == r['doi']), '不在证据库')
                             for r in art if r['pdf'] and not r['si'] and r['doi'])}
    return out


def render(c, detail=False):
    e = c['evidence']
    si = e['si']
    lines = ['# 库里有什么（%s）' % __import__('time').strftime('%Y-%m-%d %H:%M'), '',
             '## 证据库（全集，%d 篇登记）' % e['total'],
             '',
             '| | 篇 |', '|---|---|',
             '| 有正文原件 PDF | %d |' % e['pdf'],
             '| 解析过（有全文文本） | %d |' % e['fulltext'],
             '| 有精读 | %d |' % e['summary'],
             '| 有结构化记录 | %d |' % e['structured'],
             '| 没有 DOI（学位论文 / 专利 / 手动加的多在这） | %d |' % e['no_doi'],
             '| 也在 Zotero 里 | %d |' % e['in_zotero'],
             '',
             '有正文的 %d 篇里，SI 的情况：' % e['pdf'],
             '',
             '| SI | 篇 | 意思 |', '|---|---|---|',
             '| 有 | %d | 盘上有 SI 原件 |' % si.get('have', 0),
             '| 确认没有 | %d | 去出版商页面看过，没挂（综述 / 老文献常见） |' % si.get('none', 0),
             '| 没取过 | %d | 还没去出版商那里问过，或上次没取成 —— 这批是「补 SI」的对象 |' % si.get('unknown', 0),
             '']
    z = c['zotero']
    if z is None:
        lines += ['## Zotero', '', 'Zotero 没开，这一半没数。开着 Zotero 再跑一次。']
    else:
        lines += ['## Zotero（他自己挑出来读的子集，%d 条）' % z['total'], '',
                  '| 类型 | 条 |', '|---|---|']
        lines += ['| %s | %d |' % (k, n) for k, n in z['kinds'].most_common()]
        lines += ['', '| | 条 |', '|---|---|',
                  '| 没有 DOI | %d |' % z['no_doi'],
                  '| 一个 PDF 都没挂 | %d |' % z['no_pdf'],
                  '| 有 DOI 但证据库里没有 | %d |' % z['not_in_evidence'],
                  '',
                  '论文类（期刊 / 预印本 / 会议）%d 条：' % z['articles'], '',
                  '| | 条 |', '|---|---|',
                  '| 正文 + SI 都挂了 | %d |' % z['art_pdf_si'],
                  '| 只挂了正文 | %d |' % z['art_pdf_only'],
                  '| 连正文都没挂 | %d |' % z['art_no_pdf'],
                  '',
                  '「只挂了正文」的那些，证据库怎么说它的 SI：', '',
                  '| | 条 |', '|---|---|']
        lines += ['| %s | %d |' % ({'have': '证据库里其实有 SI（没推回 Zotero）', 'none': '确认没有',
                                     'unknown': '没取过'}.get(k, k), n) for k, n in z['art_pdf_only_si'].most_common()]
    if detail and z is not None:
        lines += ['', '## 明细：非论文类', '']
        for r in c['rows_zotero']:
            if r['kind'] not in ('期刊论文', '预印本', '会议论文'):
                lines.append('- [%s] %s%s' % (r['kind'], r['title'], '' if r['pdf'] else '（无 PDF）'))
    return '\n'.join(lines)


def main():
    from shared.kernel.cli import flag
    print(render(census(), detail=flag('--明细')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
