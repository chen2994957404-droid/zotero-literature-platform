# -*- coding: utf-8 -*-
"""搜全球文献库（Sciverse，4.55 亿条记录），并标出哪些你库里已有。

和 `tools/discover`（找新文献）的区别：
  这里是**纯检索**——你给什么词就搜什么词，按被引/影响力/年份精筛，看全球有什么。
  `tools/discover` 会**替你把问题拆成多个检索式 + 沿引用网络雪球 + 按「跟你多相关」排序**。
  想「看看这个词全球什么情况」用这里；想「补库、决定读哪几篇」用 discover。

用法:
  python -m tools.askworld.search "polyborosiloxane"
  python -m tools.askworld.search "dynamic boron ester elastomer" 20 --since 2021 --impact
  参数: <检索词> [数量] [--since 年份] [--impact 偏高被引 | --fresh 偏最新 | --cited 按被引排序]
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters.sciverse import SciverseError, looks_chinese
from shared.kernel.cli import flag, opt, pos
from tools import askworld


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

    if not askworld.available():
        print('未配置 SCIVERSE_KEY。请双击「控制面板.bat」，在 Sciverse 一栏填写。')
        print('（或改用不需要密钥的：python -m tools.discover "关键词" --openalex）')
        return

    # 中文检索式会把结果带偏（服务端按语言加权，材料领域好文献几乎都是英文）
    if looks_chinese(query):
        print(f'⚠ 检测到中文检索词。Sciverse 会偏向同语言文献，'
              f'材料方向建议改用英文关键词，召回质量高很多。\n')

    try:
        r = askworld.search_world(query, limit=limit, year_from=year_from, prefer=prefer)
    except SciverseError as e:
        print(f'检索失败：{e}')
        return

    items = r['items']
    have = sum(1 for it in items if it['in_library'])
    print(f'\n检索「{query}」→ 全球命中 {r["total"]} 篇，显示前 {len(items)} 篇')
    if year_from:
        print(f'（限定 {year_from} 年以后）')
    print('=' * 78)
    for i, it in enumerate(items, 1):
        mark = '【库里已有】' if it['in_library'] else '【新】      '
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
    print('\n想导入某篇：python -m tools.discover.importer <DOI>')


if __name__ == '__main__':
    main()
