# -*- coding: utf-8 -*-
"""盘点：证据库里到底有什么 —— 手上有什么（正文 / 解析 / SI 三态）。

用户 2026-09-17 问：「库里有毕业论文、专利、有 SI 的、没加 SI 的、本来就没 SI 的，有统计吗」—— 以前没有。
原来两边各数一遍（Zotero 那半按条目类型分类）；2026-10-13 Zotero 移出平台，只盘证据库。
**只读、零网络**。

用法：python -m tools.library 盘点
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from collections import Counter

from shared.kernel import catalog


def _evidence_side():
    """证据库逐篇：目录卡 + SI 三态。"""
    rows = []
    for pid in catalog.ids():
        r = catalog.record(pid)
        r['si_status'] = catalog.si_status(pid)
        rows.append(r)
    return rows


def census():
    """→ dict：汇总 + 明细行。"""
    ev = _evidence_side()
    return {'evidence': {'total': len(ev),
                         'pdf': sum(r['pdf'] for r in ev),
                         'fulltext': sum(r['fulltext'] for r in ev),
                         'no_doi': sum(1 for r in ev if not r['doi']),
                         'si': Counter(r['si_status'] for r in ev if r['pdf'])},
            'rows_evidence': ev}


def render(c, detail=False):
    e = c['evidence']
    si = e['si']
    lines = ['# 库里有什么（%s）' % __import__('time').strftime('%Y-%m-%d %H:%M'), '',
             '## 证据库（%d 篇登记）' % e['total'],
             '',
             '| | 篇 |', '|---|---|',
             '| 有正文原件 PDF | %d |' % e['pdf'],
             '| 解析过（有全文文本） | %d |' % e['fulltext'],
             '| 没有 DOI（学位论文 / 专利 / 手动加的多在这） | %d |' % e['no_doi'],
             '',
             '有正文的 %d 篇里，SI 的情况：' % e['pdf'],
             '',
             '| SI | 篇 | 意思 |', '|---|---|---|',
             '| 有 | %d | 盘上有 SI 原件 |' % si.get('have', 0),
             '| 确认没有 | %d | 去出版商页面看过，没挂（综述 / 老文献常见） |' % si.get('none', 0),
             '| 没取过 | %d | 还没去出版商那里问过，或上次没取成 —— 这批是「补 SI」的对象 |' % si.get('unknown', 0)]
    if detail:
        lines += ['', '## 明细：没有 DOI 的', '']
        lines += ['- %s %s%s' % (r['id'], r['title'][:70] or '（无标题）', '' if r['pdf'] else '（无 PDF）')
                  for r in c['rows_evidence'] if not r['doi']]
    return '\n'.join(lines)


def main():
    from shared.kernel.cli import flag
    print(render(census(), detail=flag('--明细')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
