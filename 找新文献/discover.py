# -*- coding: utf-8 -*-
"""找文献（闭环版）：搜全球 → 对照我的库 → 按「跟我多相关」排序 → 一键入库触发精读。

**和普通文献搜索的区别**：外部检索谁都能调；本工具的价值在于它知道
**你已经有什么、读过什么、在做什么方向**，所以能回答那个真正要紧的问题 ——
不是「有哪些文献」，而是「哪几篇值得我现在就读」。

排序刻意让「与我的方向相关」压过「被引数」：
一篇 300 次引用的通用综述，往往不如一篇 5 次引用但正好做你那个体系的论文。

**混合检索策略**（有实证支撑，不是拍脑袋）：

    单个数据库检索              召回 13~35%
    + 查询扩展（拆成多个检索式）  召回 50~95%
    + 前后向雪球（引用网络）      召回 90~100%   ← 本工具默认全做

两条腿缺一不可：
- **查询扩展**解决「同一个东西有多种叫法」（polyborosiloxane / PBS /
  borosiloxane elastomer / shear stiffening gel …），只搜一个词必漏。
- **雪球**解决「术语完全不同但引用上挨着」—— 关键词永远搜不到那批，
  而种子集用的是**你自己库里最相关的几篇**（这一步别人做不了）。

用法:
  python 找新文献/discover.py "polyborosiloxane dynamic bond"
  python 找新文献/discover.py "我的材料回弹太差怎么解决" --解决问题
  python 找新文献/discover.py "shear stiffening gel" 30 --since 2020
  python 找新文献/discover.py "..." --扩展 8      拆更多检索式（更全，更慢更费）
  python 找新文献/discover.py "..." --单查询      只用原话搜（快，但会漏）
  python 找新文献/discover.py "..." --种子 5      雪球用几篇种子（默认 3）
  python 找新文献/discover.py "..." --不雪球      跳过引用网络扩展（快，但召回明显下降）
  python 找新文献/discover.py "..." --all         同时显示库里已有的
  python 找新文献/discover.py "..." --openalex    改用免费的 OpenAlex（不需要密钥）

两种模式：
  默认（系统调研）求**全** —— 术语变体、同义词、上位/下位概念
  --解决问题        求**准** —— 机理、方法、性能指标、应用场景等不同角度

看完想收哪篇：python 找新文献/import_by_doi.py <DOI>
入库后在 Zotero 打「待处理」标签即自动精读。
"""
import os, sys, re, json, time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from core import paths

from modules.cli import pos, flag, opt
from modules.lib_match import match_many, rank
from modules import sciverse


def fetch_one(query, limit, year_from, use_openalex, prefer):
    """单个检索式取候选。优先 Sciverse（覆盖广），没密钥或指定时走 OpenAlex（免费）。"""
    if not use_openalex and sciverse.available():
        r = sciverse.search_papers(query, limit=limit, year_from=year_from, prefer=prefer)
        return r['items'], r['total'], 'Sciverse（4.55 亿条）'
    from modules.paper_discovery import search as oa_search
    out = []
    for it in oa_search(query, limit=limit):
        out.append({'title': it.get('title') or '', 'doi': it.get('doi') or '',
                    'year': it.get('year'), 'venue': it.get('venue') or '',
                    'citations': it.get('cited') or 0, 'abstract': it.get('abstract') or '',
                    'is_oa': it.get('is_oa'), 'oa_url': ''})
    return out, len(out), 'OpenAlex（免费）'


def _key(it):
    """合并去重用的标识：优先 DOI，没有就用归一标题。"""
    doi = (it.get('doi') or '').lower().strip()
    if doi:
        return 'doi:' + doi
    return 'ti:' + re.sub(r'[^a-z0-9]', '', (it.get('title') or '').lower())[:110]


def fetch_multi(queries, limit, year_from, use_openalex, prefer):
    """多个检索式分别检索后合并去重，并统计每一式的**新增贡献**。

    「新增贡献」是判断检索是否饱和的直接依据：
    如果最后几个检索式都只带来一两篇新的，说明这个方向基本被覆盖到了；
    如果每一式都带来大量新文献，说明还远没搜够 —— 这正面回答「全不全面」。
    """
    merged, seen, contrib, source, total_hint = [], set(), [], '', 0
    per = max(8, limit // max(1, len(queries)) + 6)   # 每式多取一些，合并后再截断
    for q in queries:
        try:
            items, total, source = fetch_one(q, per, year_from, use_openalex, prefer)
        except Exception as e:
            contrib.append((q, 0, 0, f'失败: {str(e)[:40]}'))
            continue
        total_hint = max(total_hint, total)
        new = 0
        for it in items:
            k = _key(it)
            if k in seen:
                continue
            seen.add(k)
            merged.append(it)
            new += 1
        contrib.append((q, len(items), new, ''))
    # 把 seen 一并返回：后续雪球扩展要接着用同一套去重键，否则会重复计入
    return merged, total_hint, source, contrib, seen


def run_discovery(query, limit=25, n_queries=5, mode='survey', year_from=None,
                  prefer='relevance', snowball_seeds=3, topic_floor=0.45,
                  use_openalex=False, log=None):
    """完整的混合检索流程，返回结构化结果。

    **命令行与控制面板共用本函数** —— 逻辑只有一份。
    早先 import_by_doi 就是因为逻辑写死在脚本里、无法复用，
    导致我在提示里给了一条根本无效的命令（踩坑：能被复用是脚本的基本素养）。

    log: 可选的进度回调 log(str)，面板用它做实时进度显示。
    返回 {'queries', 'contrib', 'seeds', 'snow_added', 'filtered',
          'total_pool', 'rows'}；rows 为 [(paper, match, score)] 已排序。
    """
    say = log or (lambda s: None)

    # 先从用户库里取「领域上下文」：缩写歧义只能靠它消解（踩坑 #39）。
    # 「PBS」在材料界是聚硼硅氧烷、化工界是聚丁二酸丁二醇酯、生物界是磷酸盐缓冲液。
    # **只有本平台知道这个用户属于哪一界** —— 因为只有我们有他的库。
    ctx = []
    try:
        from modules.lib_match import pick_seeds
        ctx = [s['title'] for s in pick_seeds(query, n=5) if s.get('title')]
        if ctx:
            say(f'（按你库里的方向理解：{ctx[0][:46]}…）')
    except Exception:
        pass

    queries = [query]
    if n_queries > 1:
        say(f'把问题拆成 {n_queries} 个互补检索式（{"解决问题" if mode == "problem" else "系统调研"}模式）…')
        try:
            from modules.query_expand import expand as qexpand
            queries = qexpand(query, mode=mode, n=n_queries, context=ctx)
        except Exception as e:
            say(f'扩展失败，退回单查询：{str(e)[:50]}')
            queries = [query]
        for i, q in enumerate(queries, 1):
            say(f'  {i}. {q}')

    items, total, source, contrib, seen_keys = fetch_multi(
        queries, limit, year_from, use_openalex, prefer)
    if not items:
        return {'queries': queries, 'contrib': contrib, 'seeds': [], 'snow_added': 0,
                'filtered': 0, 'total_pool': 0, 'rows': [], 'source': source}
    say(f'关键词检索合并去重后 {len(items)} 篇')

    seeds, snow_added = [], 0
    if snowball_seeds > 0:
        from modules.lib_match import pick_seeds
        from modules.snowball import expand as snowball
        # 同样用扩展式集合挑种子：原始输入可能是「PBS」这种无语义的缩写
        seeds = pick_seeds(' ; '.join(queries), n=snowball_seeds)
        if seeds:
            say(f'从你库里挑了 {len(seeds)} 篇做雪球种子，正在沿引用网络扩展…')
            try:
                sr = snowball([s['doi'] for s in seeds], direction='both', limit_per_seed=30)
                for it in sr['items']:
                    k = _key(it)
                    if k not in seen_keys:
                        seen_keys.add(k)
                        items.append(it)
                        snow_added += 1
                say(f'雪球带来 {snow_added} 篇关键词没搜到的文献')
            except Exception as e:
                say(f'雪球失败（不影响其余结果）：{str(e)[:60]}')
        else:
            say('库里没找到合适的种子，跳过雪球')

    total_pool = len(items)
    say(f'正在与你的库对照（共 {total_pool} 篇）…')
    # 贴题度用**全部扩展式拼起来**作参照，而不是用户原始输入（踩坑 #39）。
    # 用户可能只输入「PBS」这种三字母缩写 —— 它的向量没有语义，
    # 拿它当基准会把所有候选都判成不贴题，最后一篇不剩。
    # 扩展式集合才完整表达了「他到底想找什么」。
    topic_text = ' ; '.join(queries)
    ms = match_many(items, topic=topic_text)

    filtered = 0
    if topic_floor > 0:
        def _keep(floor):
            return [(p, m) for p, m in zip(items, ms)
                    if m.get('topic_sim') is None or m['topic_sim'] >= floor]
        keep = _keep(topic_floor)
        # 兜底：门槛把结果杀光时自动放宽。
        # **内部阈值永远不该让用户看到「0 篇」** —— 那看起来像「这个方向没文献」，
        # 实际是我们的参数不合适，是最容易误导人的失败方式。
        if len(keep) < max(5, len(items) * 0.05):
            for relaxed in (topic_floor - 0.1, topic_floor - 0.2, 0.0):
                keep = _keep(max(relaxed, 0.0))
                if len(keep) >= max(5, len(items) * 0.05):
                    say(f'（贴题门槛 {topic_floor} 过严，自动放宽到 {max(relaxed, 0.0):.2f}）')
                    break
        filtered = len(items) - len(keep)
        items = [p for p, _ in keep]
        ms = [m for _, m in keep]
        if filtered:
            say(f'滤掉 {filtered} 篇跨方向文献，留下 {len(items)} 篇')

    return {'queries': queries, 'contrib': contrib, 'seeds': seeds,
            'snow_added': snow_added, 'filtered': filtered,
            'total_pool': total_pool, 'source': source,
            'rows': rank(items, ms)}


def main():
    query = pos(0)
    if not query:
        print(__doc__)
        return
    p1 = pos(1)
    limit = int(p1) if p1 and p1.isdigit() else 25
    year_from = opt('--since')
    prefer = ('citations' if flag('--cited') else
              'fresh' if flag('--fresh') else
              'impact' if flag('--impact') else 'relevance')
    show_all = flag('--all')

    # 查询扩展：单一检索式是「搜不全」的根本原因（材料领域同一个东西有多种叫法）
    nq_val = opt('--扩展')
    n_q = 1 if flag('--单查询') else (int(nq_val) if nq_val and nq_val.isdigit() else 5)
    mode = 'problem' if flag('--解决问题') else 'survey'
    queries = [query]
    if n_q > 1:
        print(f'正在把问题拆成 {n_q} 个互补的检索式（{"解决问题" if mode == "problem" else "系统调研"}模式）…')
        try:
            from modules.query_expand import expand
            queries = expand(query, mode=mode, n=n_q)
        except Exception as e:
            print(f'（扩展失败，退回单查询：{str(e)[:50]}）')
            queries = [query]
        for i, q in enumerate(queries, 1):
            print(f'  {i}. {q}')
        print()

    try:
        items, total, source, contrib, seen_keys = fetch_multi(
            queries, limit, year_from, flag('--openalex'), prefer)
    except Exception as e:
        print(f'检索失败：{e}')
        return
    if not items:
        print('没有检索到结果，换个说法试试。')
        return

    # ── 雪球扩展：关键词检索必然漏掉「术语不同但引用上挨着」的文献 ──
    # 实证：单库检索召回 13~35%，优化检索式 50~95%，**再加一轮前后向雪球才到 90~100%**。
    snow_stats = []
    if not flag('--不雪球'):
        from modules.lib_match import pick_seeds
        from modules.snowball import expand as snowball
        seed_val = opt('--种子')
        seeds = pick_seeds(queries[0], n=int(seed_val) if seed_val and seed_val.isdigit() else 3)
        if seeds:
            print(f'\n从你库里挑了 {len(seeds)} 篇最相关的做雪球种子：')
            for s in seeds:
                print(f'  相似{s["sim"]}  {s["title"][:62]}')
            try:
                sr = snowball([s['doi'] for s in seeds], direction='both', limit_per_seed=30)
                snow_stats = sr['stats']
                added = 0
                for it in sr['items']:
                    k = _key(it)
                    if k in seen_keys:
                        continue
                    seen_keys.add(k)
                    items.append(it)
                    added += 1
                print(f'  → 雪球带来 {added} 篇关键词没搜到的文献')
            except Exception as e:
                print(f'  （雪球失败，不影响其余结果：{str(e)[:60]}）')
        else:
            print('\n（库里没找到合适的种子，跳过雪球；Ollama 没跑时也会这样）')

    print(f'\n来源 {source} + 引用网络，合并去重后 {len(items)} 篇')
    if len(queries) > 1:
        print('\n各检索式的新增贡献（判断搜得够不够）：')
        for q, got, new, err in contrib:
            if err:
                print(f'  {q[:52]:<54} {err}')
            else:
                print(f'  {q[:52]:<54} 取{got:3d} 新增{new:3d}')
        tail = [c[2] for c in contrib[-2:] if not c[3]]
        if tail and sum(tail) <= 2:
            print('  ↳ 最后两式几乎没带来新文献，**这个方向基本搜到底了**')
        elif tail and sum(tail) >= len(items) * 0.4:
            print('  ↳ 后面的检索式还在大量带新文献，**可能还没搜全**，可加 --扩展 8 再试')
    print('\n正在与你的库对照…（首次会稍慢，要把摘要向量化）')

    # 把本次主题传进去：雪球来的文献不保证贴题，只看「跟我的库像不像」会被带偏
    ms = match_many(items, topic=queries[0])

    # 贴题门槛：**高被引不能救一篇跑题的文献**。
    # 实测（踩坑 #38）：不设门槛时，被引 1117 的水凝胶综述、被引 483 的高熵合金
    # 会因为「跟我库里某篇沾边 + 被引高」而排到前面 —— 它们跟本次主题毫无关系。
    floor = float(opt('--贴题门槛') or 0.45)
    if not flag('--宽松'):
        keep = [(p, m) for p, m in zip(items, ms)
                if m.get('topic_sim') is None or m['topic_sim'] >= floor]
        cut = len(items) - len(keep)
        if cut:
            print(f'（滤掉 {cut} 篇贴题度低于 {floor} 的 —— 多为雪球带来的跨方向文献，'
                  f'加 --宽松 可看全部）')
        items = [p for p, _ in keep]
        ms = [m for _, m in keep]

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
        detail = ''
        if m.get('topic_sim') is not None:
            detail = f'（贴题{m["topic_sim"]} 近库{m.get("lib_sim")}）'
        src = {'backward': ' [引用源头]', 'forward': ' [跟进工作]'}.get(p.get('from'), '')
        print(f'{i:2d}. {tag}[{yr}] 相关度 {rel if rel is not None else "?"} {bar:<10} '
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

    # 把这次结果存下来，供 collect.py 按编号挑选 —— 用户不必手抄 DOI
    stash = paths.last_search()
    try:
        with open(stash, 'w', encoding='utf-8') as f:
            json.dump({'query': query, 'time': time.strftime('%Y-%m-%d %H:%M'),
                       'items': [{'n': i, 'title': p.get('title'), 'doi': p.get('doi'),
                                  'year': p.get('year'), 'citations': p.get('citations'),
                                  'relevance': m.get('relevance'), 'status': m.get('status')}
                                 for i, (p, m, s) in enumerate(shown, 1)]},
                      f, ensure_ascii=False, indent=1)
    except Exception:
        pass

    print('=' * 84)
    print('相关度 = 这篇跟你库里已有内容的接近程度（不是质量分，是"离你多近"）。')
    print()
    print('决定收哪几篇（按上面的编号，不用抄 DOI）：')
    print('  python 找新文献/collect.py 1,3,5-7          只收进库，先不精读')
    print('  python 找新文献/collect.py 1,3 --精读        收进库并立刻精读')
    print('  python 找新文献/collect.py --看              再看一遍刚才的列表')


if __name__ == '__main__':
    main()
