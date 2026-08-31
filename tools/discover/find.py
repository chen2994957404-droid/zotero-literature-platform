# -*- coding: utf-8 -*-
"""找文献的命令行入口（闭环版）：搜全球 → 对照我的库 → 排序 → 存下编号供收取。

用法:
  python -m tools.discover "polyborosiloxane dynamic bond"
  python -m tools.discover "我的材料回弹太差怎么解决" --解决问题
  python -m tools.discover "shear stiffening gel" 30 --since 2020
  python -m tools.discover "..." --扩展 8      拆更多检索式（更全，更慢更费）
  python -m tools.discover "..." --单查询      只用原话搜（快，但会漏）
  python -m tools.discover "..." --种子 5      雪球用几篇种子（默认 3）
  python -m tools.discover "..." --不雪球      跳过引用网络扩展（快，但召回明显下降）
  python -m tools.discover "..." --宽松        不按贴题度过滤
  python -m tools.discover "..." --all         同时显示库里已有的
  python -m tools.discover "..." --openalex    改用免费的 OpenAlex（不需要密钥）

两种模式：
  默认（系统调研）求**全** —— 术语变体、同义词、上位/下位概念
  --解决问题        求**准** —— 机理、方法、性能指标、应用场景等不同角度

看完想收哪几篇：python -m tools.discover.collect 1,3,5-7
入库后在 Zotero 打「待处理」标签即自动精读。
"""
import io
import json
import os
import sys
import time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import paths
from shared.kernel.cli import flag, opt, pos
from tools.discover import run_discovery


def _stash(query, shown):
    """把这次结果存下来，供 collect 按编号挑选 —— 用户不必手抄 DOI。"""
    try:
        io.open(paths.last_search(), 'w', encoding='utf-8').write(json.dumps(
            {'query': query, 'time': time.strftime('%Y-%m-%d %H:%M'),
             'items': [{'n': i, 'title': p.get('title'), 'doi': p.get('doi'),
                        'year': p.get('year'), 'citations': p.get('citations'),
                        'relevance': m.get('relevance'), 'status': m.get('status')}
                       for i, (p, m, s) in enumerate(shown, 1)]},
            ensure_ascii=False, indent=1))
    except Exception:
        pass          # 存不下只是下次不能按编号收，不该让整次检索白跑


def _print_contrib(contrib, n_items):
    """各检索式的新增贡献 —— 正面回答「搜得够不够全」。"""
    print('\n各检索式的新增贡献（判断搜得够不够）：')
    for q, got, new, err in contrib:
        if err:
            print(f'  {q[:52]:<54} {err}')
        else:
            print(f'  {q[:52]:<54} 取{got:3d} 新增{new:3d}')
    tail = [c[2] for c in contrib[-2:] if not c[3]]
    if tail and sum(tail) <= 2:
        print('  ↳ 最后两式几乎没带来新文献，**这个方向基本搜到底了**')
    elif tail and sum(tail) >= n_items * 0.4:
        print('  ↳ 后面的检索式还在大量带新文献，**可能还没搜全**，可加 --扩展 8 再试')


def main():
    query = pos(0)
    if not query:
        print(__doc__)
        return
    p1 = pos(1)
    limit = int(p1) if p1 and p1.isdigit() else 25
    prefer = ('citations' if flag('--cited') else
              'fresh' if flag('--fresh') else
              'impact' if flag('--impact') else 'relevance')
    nq_val = opt('--扩展')
    n_q = 1 if flag('--单查询') else (int(nq_val) if nq_val and nq_val.isdigit() else 5)
    seed_val = opt('--种子')
    n_seeds = 0 if flag('--不雪球') else (int(seed_val) if seed_val and seed_val.isdigit() else 3)
    floor = 0.0 if flag('--宽松') else float(opt('--贴题门槛') or 0.45)
    show_all = flag('--all')

    try:
        r = run_discovery(query, limit=limit, n_queries=n_q,
                          mode='problem' if flag('--解决问题') else 'survey',
                          year_from=opt('--since'), prefer=prefer,
                          snowball_seeds=n_seeds, topic_floor=floor,
                          use_openalex=flag('--openalex'), log=print)
    except Exception as e:
        print(f'检索失败：{e}')
        return
    if not r['rows']:
        print('没有检索到结果，换个说法试试。')
        return

    if r['seeds']:
        print('\n雪球种子（你库里跟这个方向最近的几篇）：')
        for s in r['seeds']:
            print(f'  相似{s["sim"]}  {s["title"][:62]}')
    print(f'\n来源 {r["source"]} + 引用网络，合并去重后 {r["total_pool"]} 篇')
    if len(r['queries']) > 1:
        _print_contrib(r['contrib'], r['total_pool'])

    rows = r['rows']
    n_have = sum(1 for _p, m, _s in rows if m['status'] in ('have', 'likely'))
    shown = [x for x in rows if show_all or x[1]['status'] == 'new']

    print('\n' + '=' * 84)
    print(f'库里已有 {n_have} 篇 · 新文献 {len(rows) - n_have} 篇'
          + ('' if show_all else '（下面只列新的，加 --all 可看全部）'))
    print('=' * 84)

    for i, (p, m, _score) in enumerate(shown, 1):
        tag = {'have': '【已有】', 'likely': '【疑似已有】', 'new': ''}[m['status']]
        rel = m['relevance']
        bar = '█' * int((rel or 0) * 10) if rel is not None else '?'
        detail = ''
        if m.get('topic_sim') is not None:
            detail = f'（贴题{m["topic_sim"]} 近库{m.get("lib_sim")}）'
        src = {'backward': ' [引用源头]', 'forward': ' [跟进工作]'}.get(p.get('from'), '')
        print(f'{i:2d}. {tag}[{p.get("year") or "????"}] '
              f'相关度 {rel if rel is not None else "?"} {bar:<10} '
              f'被引{p.get("citations", 0)}{detail}{src}')
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

    _stash(query, shown)

    print('=' * 84)
    print('相关度 = 这篇跟你库里已有内容的接近程度（不是质量分，是"离你多近"）。')
    print()
    print('决定收哪几篇（按上面的编号，不用抄 DOI）：')
    print('  python -m tools.discover.collect 1,3,5-7          只收进库，先不精读')
    print('  python -m tools.discover.collect 1,3 --精读        收进库并立刻精读')
    print('  python -m tools.discover.collect --看              再看一遍刚才的列表')


if __name__ == '__main__':
    main()
