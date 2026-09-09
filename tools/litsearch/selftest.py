# -*- coding: utf-8 -*-
"""litsearch 自测：纯离线，一次网都不联。

**为什么能全离线**：本工具自己不做判断，判断在 `shared/domain/libmatch`，
取数在 `shared/adapters/openalex`。留给这一层的只有「参数怎么拼、返回怎么收尾」，
那些恰好都能离线验。

测的是三条承诺：
  ① 年份范围拼成 OpenAlex 认的 filter 语法（拼错会安静地不过滤，比报错更坏）
  ② 收尾一定会截断到 limit，且一定给每条标上 in_library
  ③ 空检索词不发请求（省一次往返，也避免 OpenAlex 报 400）
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters import openalex
from tools import litsearch

_fail = []


def check(name, cond, extra=''):
    print(('  [PASS] ' if cond else '  [FAIL] ') + name + (('  ' + extra) if extra else ''))
    if not cond:
        _fail.append(name)


def main():
    print('litsearch 自测（离线）')

    # ── ① 年份 filter 的拼法 ──────────────────────────────────────────
    seen = {}

    def fake_filter(f, limit=25, sort=None, **kw):
        seen['f'] = dict(f)
        seen['limit'] = limit
        return [{'title': 'x', 'doi': '10.1/x', 'year': 2020}], 7

    real_filter, real_index = openalex.works_by_filter, litsearch.library_index
    openalex.works_by_filter = fake_filter
    litsearch.library_index = lambda: (set(), set())
    litsearch._index_cache.update({'t': 0, 'titles': set(), 'dois': set()})
    try:
        litsearch.search('borosiloxane', limit=5, year_from=2015, year_to=2020)
        check('起止年都给 → 区间语法', seen['f'].get('publication_year') == '2015-2020',
              str(seen['f'].get('publication_year')))

        litsearch.search('borosiloxane', limit=5, year_from=2015)
        check('只给起始年 → 大于语法', seen['f'].get('publication_year') == '>2014',
              str(seen['f'].get('publication_year')))

        litsearch.search('borosiloxane', limit=5, year_to=2020)
        check('只给结束年 → 小于语法', seen['f'].get('publication_year') == '<2021',
              str(seen['f'].get('publication_year')))

        litsearch.search('borosiloxane', limit=5)
        check('不给年份 → 不带年份条件', 'publication_year' not in seen['f'])
        check('检索词进的是精确检索字段',
              seen['f'].get('title_and_abstract.search') == 'borosiloxane')

        # ── ② 收尾：截断 + 一定标 in_library ─────────────────────────
        litsearch.search('x', limit=999)
        check('limit 超上限被压到 MAX_LIMIT', seen['limit'] == litsearch.MAX_LIMIT,
              f"limit={seen['limit']}")

        items, total = litsearch.search('x', limit=5)
        check('总命中数原样透出（判断该不该收窄靠它）', total == 7, f'total={total}')
        check('每条都标了 in_library', all('in_library' in it for it in items))

        # ── ③ 空检索词不发请求 ───────────────────────────────────────
        seen.clear()
        items, total = litsearch.search('   ', limit=5)
        check('空检索词直接返回，不发请求', not seen and items == [] and total == 0)
    finally:
        openalex.works_by_filter, litsearch.library_index = real_filter, real_index
        litsearch._index_cache.update({'t': 0, 'titles': set(), 'dois': set()})

    # ── 收尾函数本身 ─────────────────────────────────────────────────
    rows = litsearch._finish(
        [{'title': 'A', 'doi': '10.1/a'}, {'title': 'B', 'doi': '10.1/b'}], 1)
    check('_finish 截断到 limit', len(rows) == 1)

    total = 10
    print(f'\n  {total - len(_fail)}/{total} 通过')
    return 1 if _fail else 0


if __name__ == '__main__':
    sys.exit(main())
