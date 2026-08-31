# -*- coding: utf-8 -*-
"""discover · 找新文献：搜全球 → 对照我的库 → 按「跟我多相关」排序 → 收进库。

**和普通文献搜索的区别**：外部检索谁都能调（OpenAlex、Sciverse 都是公开 API）。
本工具的价值在于它知道**你已经有什么、读过什么、在做什么方向**，
所以能回答那个真正要紧的问题 —— 不是「有哪些文献」，而是「哪几篇值得我现在就读」。

排序刻意让「与我的方向相关」压过「被引数」：
一篇 300 次引用的通用综述，往往不如一篇 5 次引用但正好做你那个体系的论文。

**混合检索策略**（有实证支撑，不是拍脑袋）：

    单个数据库检索              召回 13~35%
    + 查询扩展（拆成多个检索式）  召回 50~95%
    + 前后向雪球（引用网络）      召回 90~100%   ← 默认全做

两条腿缺一不可：
- **查询扩展**解决「同一个东西有多种叫法」（polyborosiloxane / PBS /
  borosiloxane elastomer / shear stiffening gel …），只搜一个词必漏。
- **雪球**解决「术语完全不同但引用上挨着」—— 关键词永远搜不到那批，
  而种子集用的是**你自己库里最相关的几篇**（这一步别人做不了）。

**对外契约**（别的地方只许调这些；`cli.py` / `mcp.py` 也只许调这些）：

| 入口 | 干什么 |
|---|---|
| `run_discovery(query, ...)` | **主入口**：完整混合检索，返回排好序的结构化结果 |
| `search(query, limit)`      | 只搜 OpenAlex 一次（便宜、不花 LLM 额度），标出库里已有 |
| `match.match_many/rank/pick_seeds` | 与我的库对照、排序、挑雪球种子 |
| `importer.import_dois(dois, tags)` | 按 DOI 收进 Zotero（**写操作**，带角色守卫）|

**命令行与控制面板共用 `run_discovery`** —— 逻辑只有一份。

它组合了什么：
    shared.adapters.query_expand（拆检索式） + shared.adapters.sciverse / openalex（检索）
  + shared.adapters.snowball（沿引用网络扩展） + 本工具的 match（与我的库对照）
"""
import re

from shared.adapters import openalex, sciverse
from shared.adapters.zotero_client import library_index

from tools.discover.match import match_many, pick_seeds, rank


def search(query, limit=25, mailto='research@example.com'):
    """按检索词搜 OpenAlex 一次，返回文献列表，并标出哪些库里已经有了。

    **检索本身交给 shared.adapters.openalex**，这里只做「外部结果 × 我的库」这一步。
    要「找得全」用 `run_discovery`，这个只是最便宜的一次性检索。
    """
    have_titles, have_dois = library_index()
    items, _total = openalex.search(query, limit=limit, mailto=mailto)
    for it in items:
        tnorm = re.sub(r'[^a-z0-9]', '', (it.get('title') or '').lower())
        it['in_library'] = (tnorm in have_titles) or ((it.get('doi') or '').lower() in have_dois)
    return items


def fetch_one(query, limit, year_from, use_openalex, prefer):
    """单个检索式取候选。优先 Sciverse（覆盖广），没密钥或指定时走 OpenAlex（免费）。"""
    if not use_openalex and sciverse.available():
        r = sciverse.search_papers(query, limit=limit, year_from=year_from, prefer=prefer)
        return r['items'], r['total'], 'Sciverse（4.55 亿条）'
    out = []
    for it in search(query, limit=limit):
        out.append({'title': it.get('title') or '', 'doi': it.get('doi') or '',
                    'year': it.get('year'), 'venue': it.get('venue') or '',
                    # ⚠ 字段名必须是 citations：曾经这里读 'cited'、上游发 'cited_by'，
                    #   两边对不上，导致走 OpenAlex 时引用数永远是 0（阶段 2 修）
                    'citations': it.get('citations') or 0, 'abstract': it.get('abstract') or '',
                    'is_oa': it.get('is_oa'), 'oa_url': it.get('oa_url') or ''})
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


def snowball_more(queries, items, seen_keys, n_seeds=3, limit_per_seed=30, say=None):
    """从库里挑种子做雪球扩展，把新文献并进 items（原地改）。

    返回 (seeds, 新增篇数)。种子挑不出来或雪球失败都只是少几篇，**不影响其余结果**。
    """
    say = say or (lambda s: None)
    from shared.adapters.snowball import expand as snowball
    # 用扩展式集合挑种子：原始输入可能是「PBS」这种无语义的缩写
    seeds = pick_seeds(' ; '.join(queries), n=n_seeds)
    if not seeds:
        say('库里没找到合适的种子，跳过雪球（Ollama 没跑时也会这样）')
        return [], 0
    say(f'从你库里挑了 {len(seeds)} 篇做雪球种子，正在沿引用网络扩展…')
    added = 0
    try:
        sr = snowball([s['doi'] for s in seeds], direction='both',
                      limit_per_seed=limit_per_seed)
        for it in sr['items']:
            k = _key(it)
            if k not in seen_keys:
                seen_keys.add(k)
                items.append(it)
                added += 1
        say(f'雪球带来 {added} 篇关键词没搜到的文献')
    except Exception as e:
        say(f'雪球失败（不影响其余结果）：{str(e)[:60]}')
    return seeds, added


def run_discovery(query, limit=25, n_queries=5, mode='survey', year_from=None,
                  prefer='relevance', snowball_seeds=3, topic_floor=0.45,
                  use_openalex=False, log=None):
    """完整的混合检索流程，返回结构化结果。

    **命令行与控制面板共用本函数** —— 逻辑只有一份。
    早先 import_by_doi 就是因为逻辑写死在脚本里、无法复用，
    导致我在提示里给了一条根本无效的命令（教训：能被复用是脚本的基本素养）。

    log: 可选的进度回调 log(str)，面板用它做实时进度显示。
    返回 {'queries', 'contrib', 'seeds', 'snow_added', 'filtered',
          'total_pool', 'source', 'rows'}；rows 为 [(paper, match, score)] 已排序。
    """
    say = log or (lambda s: None)

    # 先从用户库里取「领域上下文」：缩写歧义只能靠它消解（踩坑 #39）。
    # 「PBS」在材料界是聚硼硅氧烷、化工界是聚丁二酸丁二醇酯、生物界是磷酸盐缓冲液。
    # **只有本平台知道这个用户属于哪一界** —— 因为只有我们有他的库。
    ctx = []
    try:
        ctx = [s['title'] for s in pick_seeds(query, n=5) if s.get('title')]
        if ctx:
            say(f'（按你库里的方向理解：{ctx[0][:46]}…）')
    except Exception:
        pass

    queries = [query]
    if n_queries > 1:
        say(f'把问题拆成 {n_queries} 个互补检索式（{"解决问题" if mode == "problem" else "系统调研"}模式）…')
        try:
            from shared.adapters.query_expand import expand as qexpand
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
        seeds, snow_added = snowball_more(queries, items, seen_keys,
                                          n_seeds=snowball_seeds, say=say)

    total_pool = len(items)
    say(f'正在与你的库对照（共 {total_pool} 篇）…')
    # 贴题度用**全部扩展式拼起来**作参照，而不是用户原始输入（踩坑 #39）。
    # 用户可能只输入「PBS」这种三字母缩写 —— 它的向量没有语义，
    # 拿它当基准会把所有候选都判成不贴题，最后一篇不剩。
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
