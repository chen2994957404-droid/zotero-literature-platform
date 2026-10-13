# -*- coding: utf-8 -*-
"""library 自测：不联网、不依赖用户数据，验渲染与检索的纯逻辑。

2026-10-13 Zotero 移出平台：原来测的是 Zotero 条目 / 合集 / 标签的渲染和「最近 N 天」，那几个函数都删了。
现在测证据库那一半的渲染，以及检索（dbsearch）的归一与 DOI 识别。
"""
import os, sys
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass
from tools import library
from tools.library import dbsearch

ROWS = [{'id': 'doi_10.1000-x', 'doi': '10.1000/x', 'title': 'A boron elastomer', 'year': 2024,
         'pdf': True, 'si': False, 'fulltext': True, 'summary': False, 'structured': True}]


def main():
    ok = total = 0

    def check(name, cond, detail=''):
        nonlocal ok, total
        total += 1
        if cond:
            ok += 1
            print(f'  [PASS] {name}')
        else:
            print(f'  [FAIL] {name} {detail}')

    t = library.render_db(ROWS)
    check('证据库渲染：带 id、标题、DOI', 'doi_10.1000-x' in t and 'A boron elastomer' in t and '10.1000/x' in t, t)
    check('证据库渲染：手上有什么的标记', '[正·析·构]' in t or '正' in t, t)
    check('检索：DOI 识别', dbsearch.is_doi('10.1021/acs.macromol.6c00733') and not dbsearch.is_doi('boron'))
    check('检索：文件夹名写法也归成同一串',
          dbsearch.doi_key('doi_10.1021-acs.macromol') in dbsearch.doi_key('10.1021/acs.macromol.6c00733'))
    check('检索：连字符与大小写不影响', dbsearch.norm('Shu-Hong Yu') == dbsearch.norm('shuhong yu'))

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
