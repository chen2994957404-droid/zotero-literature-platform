# -*- coding: utf-8 -*-
"""对抗式检索取原料的命令行入口（只解析参数，一行业务逻辑都没有）。

用法:
    python -m tools.litsearch "borosiloxane"                     # 精确检索
    python -m tools.litsearch "\\"boronic acid\\" AND silanol" --limit 40
    python -m tools.litsearch "borosiloxane" --since 2015 --until 2026
    python -m tools.litsearch --abstract 10.1021/ma500632f       # 取完整摘要
    python -m tools.litsearch --cited-by 10.1021/cm980353l       # 谁引了这篇
    python -m tools.litsearch --references 10.1021/cm980353l     # 这篇引了谁

全部免费、只读、不写 Zotero。要收进库用 `python -m tools.getpdf <DOI> --to-zotero`。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel.cli import flag, opt, positionals, wants_help
from tools import litsearch


def _line(it):
    mark = '【库里有】' if it.get('in_library') else '         '
    return '%s [%s] 被引%-5s %s\n           %s | %s' % (
        mark, it.get('year') or '????', it.get('citations') or 0,
        (it.get('title') or '')[:78], (it.get('venue') or '?')[:40],
        it.get('doi') or '(无 DOI)')


def _show(items):
    if not items:
        print('（没有结果）')
        return
    for it in items:
        print(_line(it))


def main():
    # 有分支的入口先认 --help，别让不认识的参数走进最贵那条路（强制规范 #2）
    if wants_help():
        print(__doc__)
        return 0

    doi = opt('--abstract') or opt('--cited-by') or opt('--references')
    limit = int(opt('--limit') or 25)

    if opt('--abstract'):
        it = litsearch.abstract(opt('--abstract'))
        if not it:
            print('查不到这个 DOI（OpenAlex 没收录，或 DOI 写错了）。')
            return 1
        print(_line(it))
        print('\n摘要：\n' + (it.get('abstract') or '(这篇没有摘要)'))
        return 0

    if opt('--cited-by'):
        print(f'谁引用了 {doi}（前向雪球）：')
        _show(litsearch.cited_by(doi, limit=limit))
        return 0

    if opt('--references'):
        print(f'{doi} 引用了谁（后向雪球）：')
        _show(litsearch.references(doi, limit=limit))
        return 0

    terms = positionals()
    if not terms:
        print(__doc__)
        return 0
    term = ' '.join(terms)
    items, total = litsearch.search(
        term, limit=limit,
        year_from=opt('--since') and int(opt('--since')),
        year_to=opt('--until') and int(opt('--until')))
    print(f'检索词「{term}」：全世界命中 {total} 篇，返回前 {len(items)} 篇')
    if total > len(items):
        print('（命中远多于返回，说明这个词还宽 —— 可以收窄，或提高 --limit 把它捞干净）')
    print()
    _show(items)
    return 0


if __name__ == '__main__':
    sys.exit(main())
