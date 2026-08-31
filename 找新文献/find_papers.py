# -*- coding: utf-8 -*-
"""供Claude调用：按检索词去 OpenAlex 取真实文献，返回给Claude判断筛选。
用法: python find_papers.py "检索词" [数量]
（2026-08-11 按 docs/代码规范_标准脚本模板.md 统一：函数化 + shared/kernel/cli 取参 + 标准开头）
"""
import os, sys, re, json, urllib.request

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel.cli import pos
from shared.adapters import openalex
from shared.kernel.config import need_site, get_site


def _norm(text):
    """标题归一化：小写 + 去非字母数字，用于「库里是否已有」比对。"""
    return re.sub(r'[^a-z0-9]', '', (text or '').lower())


def fetch_library_snapshot():
    """从本机 Zotero 取已有文献的标题/DOI 集合。

    Zotero 没开或配置缺失时返回空集合 —— 只损失「已在库」标记，检索本身不受影响。
    """
    have_titles, have_dois = set(), set()
    try:
        uid = need_site('ZOTERO_USER_ID')
        base = get_site('ZOTERO_API_HOST') + f'/api/users/{uid}'
        headers = {'Zotero-Allowed-Request': 'true'}
        start = 0
        while True:
            url = f'{base}/items/top?limit=100&start={start}'
            req = urllib.request.Request(url, headers=headers)
            data = json.loads(urllib.request.urlopen(req, timeout=15).read())
            if not data:
                break
            for item in data:
                fields = item.get('data', {})
                title = _norm(fields.get('title'))
                if title:
                    have_titles.add(title)
                doi = (fields.get('DOI') or '').lower()
                if doi:
                    have_dois.add(doi)
            start += 100
            if len(data) < 100:
                break
    except Exception:
        pass  # 本机 Zotero 未开/未配：只做纯检索，「已在库」标记留空
    return have_titles, have_dois
def main():
    query = pos(0)
    if not query:
        print('用法: python find_papers.py "检索词" [数量]')
        sys.exit(1)
    limit = int(pos(1) or 8)

    have_titles, have_dois = fetch_library_snapshot()
    works, total = openalex.search(query, limit=limit)

    print(f'检索「{query}」共 {total} 篇，返回 {len(works)} 篇：')
    print()
    for i, w in enumerate(works, 1):
        doi = w['doi']
        au_str = (w['first_author'] + ' 等') if w['first_author'] else ''
        has = (_norm(w['title']) in have_titles) or (doi.lower() in have_dois)
        mark = '【已在库】' if has else '【新】'
        print(f"{i}. {mark} [{w['year']}] {w['title']}")
        print(f"   {au_str} | {w['venue'][:30]} | 引用{w['citations']} | "
              f"{'OA可下' if w['is_oa'] else '需订阅'} | DOI:{doi}")
        if w['abstract']:
            print(f"   摘要: {w['abstract'][:220]}...")
        print()


if __name__ == '__main__':
    main()
