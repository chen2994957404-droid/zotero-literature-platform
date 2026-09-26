# -*- coding: utf-8 -*-
"""对抗式检索取原料的命令行入口（只解析参数，一行业务逻辑都没有）。

用法:
    python -m tools.litsearch "borosiloxane"                     # 精确检索
    python -m tools.litsearch "\\"boronic acid\\" AND silanol" --limit 40
    python -m tools.litsearch "borosiloxane" --since 2015 --until 2026
    python -m tools.litsearch --abstract 10.1021/ma500632f       # 取完整摘要
    python -m tools.litsearch --cited-by 10.1021/cm980353l       # 谁引了这篇
    python -m tools.litsearch --references 10.1021/cm980353l     # 这篇引了谁
    python -m tools.litsearch --semantic "a paragraph describing the work" --since 2023 [--slice]
    python -m tools.litsearch --like 10.1/a,10.1/b --since 2024  # 照着这几篇按意思找
    python -m tools.litsearch --snowball 10.1/a,10.1/b --since 2023 --newest
    python -m tools.litsearch --status 台账名                     # 看台账：饱和曲线、渠道重叠、估计
    python -m tools.litsearch --terms 台账名                      # 从判为相关的里挖新说法
    （任何检索加 --session 台账名 即记账；判断相关请走 MCP 的 lit_judge）

全部免费、只读、不写 Zotero。要收进库用 `python -m tools.getpdf <DOI> --to-zotero`。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.kernel.cli import flag, opt, positionals, wants_help
from tools import litsearch
from tools.litsearch import session as ledger


def _line(it):
    mark = '【库里有】' if it.get('in_library') else '         '
    if not it.get('has_abstract', True):
        mark += '【无摘要】'
    if it.get('seed_links'):
        mark += '[连%d个种子]' % it['seed_links']
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
    session = opt('--session')
    since = int(opt('--since') or 0) or None
    until = int(opt('--until') or 0) or None

    if opt('--status'):
        import json
        print(json.dumps(ledger.status(opt('--status')), ensure_ascii=False, indent=1))
        return 0

    if opt('--terms'):
        m = ledger.mine_terms(opt('--terms'))
        for t in m['phrases'] + m['words']:
            print('%-40s z=%-6s %d 篇' % (t['term'], t['z'], t['docs']))
        if not m['terms']:
            print('还挖不出新词：判为相关的有 %d 篇' % m['n_relevant'])
        return 0

    if opt('--semantic') or opt('--like'):
        items, info = litsearch.semantic(
            text=opt('--semantic') or '', like=[d for d in (opt('--like') or '').split(',') if d],
            year_from=since, year_to=until, slice_by_year=flag('--slice'), limit=limit, session=session)
        print('按意思检索：发了 %d 次，合并后 %d 篇，列前 %d 篇（每次最多 50 条、不按年份排）'
              % (info['calls'], info['pool'], len(items)))
        _show(items)
        return 0

    if opt('--snowball'):
        items, stats = litsearch.snowball_many(
            [d for d in (opt('--snowball') or '').split(',') if d], direction=opt('--direction') or 'both',
            year_from=since, newest_first=flag('--newest'), limit=limit, session=session)
        for d, b, f, _n in stats:
            print('种子 %s：后向 %d · 前向 %d' % (d, b, f))
        _show(items)
        return 0

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
        _show(litsearch.cited_by(doi, limit=limit, year_from=since, newest_first=flag('--newest'),
                                 session=session))
        return 0

    if opt('--references'):
        print(f'{doi} 引用了谁（后向雪球）：')
        _show(litsearch.references(doi, limit=limit, year_from=since, session=session))
        return 0

    terms = positionals()
    if not terms:
        print(__doc__)
        return 0
    term = ' '.join(terms)
    items, total = litsearch.search(term, limit=limit, year_from=since, year_to=until, session=session)
    print(f'检索词「{term}」：全世界命中 {total} 篇，返回前 {len(items)} 篇')
    if total > len(items):
        print('（命中远多于返回，说明这个词还宽 —— 可以收窄，或提高 --limit 把它捞干净）')
    print()
    _show(items)
    return 0


if __name__ == '__main__':
    sys.exit(main())
