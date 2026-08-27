# -*- coding: utf-8 -*-
"""搜全球文献库（Sciverse，4.55 亿条记录），并标出哪些你库里已有。

和同目录的 find_papers.py 的区别：
  find_papers.py    → 走 OpenAlex（免费、无需密钥）
  search_global.py  → 走 Sciverse（覆盖更广、可按被引/影响力精筛，需密钥）
两者并存不冲突：没配 Sciverse 密钥时用前者，配了就用这个。

用法:
  python 找新文献/search_global.py "polyborosiloxane"
  python 找新文献/search_global.py "dynamic boron ester elastomer" 20 --since 2021 --impact
  参数: <检索词> [数量] [--since 年份] [--impact 偏高被引 | --fresh 偏最新 | --cited 按被引排序]
"""
import os, sys, re

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from core.cli import pos, flag, opt
from adapters.sciverse import search_papers, available, looks_chinese, SciverseError


def library_index():
    """库里已有文献的标题/DOI，用于标记「已有」。复用 paper_discovery 的实现，不重写。"""
    try:
        from pipelines.paper_discovery import _library_index
        return _library_index()
    except Exception:
        return set(), set()


def norm(t):
    return re.sub(r'[^a-z0-9]', '', (t or '').lower())


def main():
    query = pos(0)
    if not query:
        print(__doc__)
        return

    p1 = pos(1)
    limit = int(p1) if p1 and p1.isdigit() else 20
    year_from = opt('--since')
    prefer = ('citations' if flag('--cited') else
              'impact' if flag('--impact') else
              'fresh' if flag('--fresh') else 'relevance')

    if not available():
        print('未配置 SCIVERSE_KEY。请双击「控制面板.bat」，在 Sciverse 一栏填写。')
        print('（或改用不需要密钥的：python 找新文献/find_papers.py "关键词"）')
        return

    # 中文检索式会把结果带偏（服务端按语言加权，材料领域好文献几乎都是英文）
    if looks_chinese(query):
        print(f'⚠ 检测到中文检索词。Sciverse 会偏向同语言文献，'
              f'材料方向建议改用英文关键词，召回质量高很多。\n')

    try:
        r = search_papers(query, limit=limit, year_from=year_from, prefer=prefer)
    except SciverseError as e:
        print(f'检索失败：{e}')
        return

    titles, dois = library_index()
    items = r['items']
    have = 0
    print(f'\n检索「{query}」→ 全球命中 {r["total"]} 篇，显示前 {len(items)} 篇')
    if year_from:
        print(f'（限定 {year_from} 年以后）')
    print('=' * 78)
    for i, it in enumerate(items, 1):
        in_lib = (it['doi'] and it['doi'].lower() in dois) or (norm(it['title']) in titles)
        have += bool(in_lib)
        mark = '【库里已有】' if in_lib else '【新】      '
        yr = it['year'] or '????'
        print(f'{i:2d}. {mark} [{yr}] 被引{it["citations"]:<5} {it["title"][:62]}')
        meta = []
        if it['venue']:
            meta.append(it['venue'][:40])
        if it['doi']:
            meta.append(f'DOI:{it["doi"]}')
        if it['is_oa']:
            meta.append('开放获取')
        if meta:
            print(f'              {" · ".join(meta)}')
    print('=' * 78)
    print(f'其中库里已有 {have} 篇，新的 {len(items) - have} 篇')
    print('\n想导入某篇：python 找新文献/import_by_doi.py <DOI>')


if __name__ == '__main__':
    main()
