# -*- coding: utf-8 -*-
"""paper_discovery 自测：用真实检索词验证返回结构。
用法: python modules/paper_discovery/selftest.py
需联网（OpenAlex）。Zotero 开着则能测 in_library 标记。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from modules.paper_discovery import search

def main():
    try:
        results = search("polyborosiloxane self-healing elastomer", limit=5)
    except Exception as e:
        print(f'  [FAIL] 搜索出错（联网？）: {e}'); sys.exit(1)

    if not results:
        print('  [FAIL] 无结果'); sys.exit(1)

    r0 = results[0]
    need = {'title', 'doi', 'year', 'abstract', 'cited_by', 'is_oa', 'in_library'}
    if need.issubset(r0.keys()):
        n_lib = sum(1 for r in results if r['in_library'])
        print(f'  [PASS] 返回 {len(results)} 篇，字段完整')
        print(f'         示例: [{r0["year"]}] {r0["title"][:45]}')
        print(f'         库里已有: {n_lib}/{len(results)} 篇')
        sys.exit(0)
    else:
        print(f'  [FAIL] 字段缺失: {need - set(r0.keys())}'); sys.exit(1)

if __name__ == '__main__':
    main()
