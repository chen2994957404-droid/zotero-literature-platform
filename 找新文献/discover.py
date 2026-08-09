# -*- coding: utf-8 -*-
"""找文献（闭环版）：搜全球 → 对照我的库 → 按「跟我多相关」排序 → 一键入库触发精读。

**和普通文献搜索的区别**：外部检索谁都能调；本工具的价值在于它知道
**你已经有什么、读过什么、在做什么方向**，所以能回答那个真正要紧的问题 ——
不是「有哪些文献」，而是「哪几篇值得我现在就读」。

排序刻意让「与我的方向相关」压过「被引数」：
一篇 300 次引用的通用综述，往往不如一篇 5 次引用但正好做你那个体系的论文。

用法:
  python 找新文献/discover.py "polyborosiloxane dynamic bond"
  python 找新文献/discover.py "shear stiffening gel" 30 --since 2020
  python 找新文献/discover.py "..." --all        同时显示库里已有的（默认只显示新的）
  python 找新文献/discover.py "..." --openalex   改用免费的 OpenAlex（不需要密钥）

看完想收哪篇：python 找新文献/import_by_doi.py <DOI>
入库后在 Zotero 打「待处理」标签即自动精读。
"""
import sys, os, io

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from modules.lib_match import match_many, rank
from modules import sciverse


def fetch(query, limit, year_from, use_openalex, prefer):
    """取候选文献。优先 Sciverse（覆盖广），没密钥或指定时走 OpenAlex（免费）。"""
    if not use_openalex and sciverse.available():
        if sciverse.looks_chinese(query):
            print('⚠ 中文检索词会让结果跑偏（服务端按语言加权，材料方向好文献几乎都是英文）。\n'
                  '  建议改用英文关键词。\n')
        r = sciverse.search_papers(query, limit=limit, year_from=year_from, prefer=prefer)
        return r['items'], r['total'], 'Sciverse（4.55 亿条）'
    from modules.paper_discovery import search as oa_search
    items = oa_search(query, limit=limit)
    out = []
    for it in items:
        out.append({'title': it.get('title') or '', 'doi': it.get('doi') or '',
                    'year': it.get('year'), 'venue': it.get('venue') or '',
                    'citations': it.get('cited') or 0, 'abstract': it.get('abstract') or '',
                    'is_oa': it.get('is_oa'), 'oa_url': ''})
    return out, len(out), 'OpenAlex（免费）'


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]
    if not args:
        print(__doc__)
        return
    query = args[0]
    limit = int(args[1]) if len(args) > 1 and args[1].isdigit() else 25
    year_from = None
    if '--since' in sys.argv:
        i = sys.argv.index('--since')
        if i + 1 < len(sys.argv):
            year_from = sys.argv[i + 1]
    prefer = ('citations' if '--cited' in flags else
              'fresh' if '--fresh' in flags else
              'impact' if '--impact' in flags else 'relevance')
    show_all = '--all' in flags

    print(f'检索「{query}」…')
    try:
        items, total, source = fetch(query, limit, year_from, '--openalex' in flags, prefer)
    except Exception as e:
        print(f'检索失败：{e}')
        return
    if not items:
        print('没有检索到结果，换个说法试试。')
        return
    print(f'来源 {source}，命中 {total} 篇，取回 {len(items)} 篇')
    print('正在与你的库对照…（首次会稍慢，要把摘要向量化）')

    ms = match_many(items)
    rows = rank(items, ms)

    n_have = sum(1 for m in ms if m['status'] in ('have', 'likely'))
    shown = [r for r in rows if show_all or r[1]['status'] == 'new']

    print('\n' + '=' * 84)
    print(f'库里已有 {n_have} 篇 · 新文献 {len(items) - n_have} 篇'
          + ('' if show_all else '（下面只列新的，加 --all 可看全部）'))
    print('=' * 84)

    for i, (p, m, score) in enumerate(shown, 1):
        tag = {'have': '【已有】', 'likely': '【疑似已有】', 'new': ''}[m['status']]
        rel = m['relevance']
        bar = '█' * int((rel or 0) * 10) if rel is not None else '?'
        yr = p.get('year') or '????'
        print(f'{i:2d}. {tag}[{yr}] 相关度 {rel if rel is not None else "?"} {bar:<10} '
              f'被引{p.get("citations", 0)}')
        print(f'    {(p.get("title") or "")[:76]}')
        meta = []
        if p.get('venue'):
            meta.append(p['venue'][:38])
        if p.get('doi'):
            meta.append(f'DOI:{p["doi"]}')
        if p.get('is_oa'):
            meta.append('开放获取')
        if meta:
            print(f'    {" · ".join(meta)}')
        if m.get('nearest') and m['status'] == 'new' and (rel or 0) >= 0.7:
            print(f'    ↳ 与你库中《{m["nearest"]["title"]}》最接近')
        print()

    print('=' * 84)
    print('相关度 = 这篇跟你库里已有内容的接近程度（不是质量分）。')
    print('想收某篇：python 找新文献/import_by_doi.py <DOI>')
    print('入库后在 Zotero 打「待处理」标签，会自动精读。')


if __name__ == '__main__':
    main()
