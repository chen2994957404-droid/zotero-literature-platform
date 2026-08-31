# -*- coding: utf-8 -*-
"""lib_match · 文献对照基础件（公理：一篇外部文献 → 它与我的库是什么关系）

**这块是整个找文献平台的价值核心。**

外部检索谁都能调（OpenAlex、Sciverse 都是公开 API）。真正不可替代的是：
**只有本平台知道用户已经有什么、读过什么、在做什么方向。**
把外部结果和本地库对照这一步做好，搜索才从「又一个 Google Scholar」
变成「知道我在干什么的助手」。

回答两个不同的问题（**别混为一谈**）：
  1. 「这篇我有没有？」   → 去重，避免重复导入
  2. 「这篇值不值得读？」 → 相关度，决定看不看

第 2 个问题才是搜回 250 篇时真正要的。
**注意：高被引 ≠ 对你有用。** 一篇 300 次引用的通用综述，
可能远不如一篇 5 次引用但正好做你那个体系的论文。
相关度必须用「离我已有的东西有多近」来定义，而这只有本地库算得出来。

对外接口：
  - build_index()          → 拉本地库索引（DOI/标题），可缓存复用
  - match(paper)           → 单篇对照
  - match_many(papers)     → 批量对照（批量向量化，省调用）
  - Ollama 没跑时自动降级为「只做精确去重」，不阻断主流程

依赖：shared.adapters.embed（本地 bge-m3，免费）、shared.adapters.zotero_client、shared.adapters.vectordb。
"""
import os, sys, re, time
from shared.kernel import paths


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VECTOR_DB = paths.VECTOR_DB

# 判定阈值（实测可调）。语义相似度用 1-余弦距离。
DUP_SIM = 0.92        # 高于此值 + 标题也像 → 基本可断定是同一篇（换了写法）
STRONG_SIM = 0.75     # 高于此值 → 与我的方向强相关，值得优先看
_index_cache = {'t': 0, 'titles': set(), 'dois': set()}
CACHE_TTL = 300       # 库索引缓存 5 分钟，避免一次批量对照反复拉 Zotero


def norm_title(t):
    """标题归一：去标点、空白、大小写。用于精确层比对。"""
    return re.sub(r'[^a-z0-9]', '', (t or '').lower())


def build_index(force=False):
    """取本地库的标题/DOI 集合。Zotero 没开时返回空集（降级，不报错）。"""
    now = time.time()
    if not force and _index_cache['t'] and now - _index_cache['t'] < CACHE_TTL:
        return _index_cache['titles'], _index_cache['dois']
    titles, dois = set(), set()
    try:
        from shared.adapters.zotero_client import zget, USER_ID
        start = 0
        while True:
            d = zget(f'/users/{USER_ID}/items/top?limit=100&start={start}')
            if not d:
                break
            for x in d:
                t = norm_title(x['data'].get('title'))
                if t:
                    titles.add(t)
                if x['data'].get('DOI'):
                    dois.add(x['data']['DOI'].lower().strip())
            start += 100
            if len(d) < 100:
                break
    except Exception:
        pass      # Zotero 没开：降级为「只靠语义层」，而不是整个功能失效
    _index_cache.update({'t': now, 'titles': titles, 'dois': dois})
    return titles, dois


def _collection():
    """取向量库。拿不到返回 None（降级为只做精确去重，而不是整个功能失效）。"""
    try:
        from shared.adapters import vectordb
        return vectordb.open_store()
    except Exception:
        return None


def _text_of(paper):
    """用于向量化的文本：标题 + 摘要。摘要是判断方向相关性的主要信息源。"""
    return f"{paper.get('title') or ''}. {(paper.get('abstract') or '')[:1500]}".strip()


def match_many(papers, top_n=3, topic=None):
    """批量对照。返回与输入等长的列表，每项：

      status    : 'have'(库里已有) / 'likely'(极可能重复) / 'new'(新的)
      relevance : 0~1，与我的库/方向的接近度；语义不可用时为 None
      nearest   : 最接近的那篇 {'title','sim'}，用于让用户理解为什么这么判

    **批量向量化**：一次把所有候选送去 embed，而不是逐篇调用 ——
    搜回 200 篇时，逐篇调用会慢几十倍。
    """
    titles, dois = build_index()
    results = [{'status': 'new', 'relevance': None, 'nearest': None} for _ in papers]

    # ── 第一层：精确去重（DOI / 归一标题）。便宜且确定，先做 ──
    pending = []
    for i, p in enumerate(papers):
        doi = (p.get('doi') or '').lower().strip()
        if doi and doi in dois:
            results[i]['status'] = 'have'
        elif norm_title(p.get('title')) and norm_title(p.get('title')) in titles:
            results[i]['status'] = 'have'
        pending.append(i)      # 已有的也算相关度，便于理解「我这个方向抓得准不准」

    # ── 第二层：语义对照 ──
    coll = _collection()
    if coll is None or not pending:
        return results
    try:
        from shared.adapters.embed import embed as embed_batch
        texts = [_text_of(papers[i]) for i in pending]
        # topic 一并向量化：**只看「跟我的库像不像」是不够的**（踩坑 #38）。
        # 关键词检索的结果天然贴题（是搜出来的），但雪球来的只保证「跟种子有引用关系」，
        # 一篇文章的参考文献什么方向都有 —— 于是水凝胶综述、摩擦纳米发电机
        # 也能因为跟库里某篇沾边而排到最前面。必须同时看「跟本次主题」的距离。
        vecs = embed_batch(([topic] if topic else []) + texts)
    except Exception:
        return results          # Ollama 没跑 → 保留精确层结果，不报错
    tvec = vecs.pop(0) if topic else None

    for idx, i in enumerate(pending):
        try:
            hits = coll.query(vecs[idx], n=top_n)
            if not hits:
                continue
            metas = [h['meta'] for h in hits]
            # 适配层已经把「距离」统一成了「越大越像」的 sim
            lib_sim = round(hits[0]['sim'], 3)
            results[i]['lib_sim'] = lib_sim
            if tvec is not None:
                ts = _cos(vecs[idx], tvec)
                results[i]['topic_sim'] = round(ts, 3)
                # 取两者的**几何平均**：任意一边低都会明显拉低总分。
                # 用几何平均而非算术平均，是因为「跟主题无关但跟我的库沾边」
                # 这种情况必须被压下去，算术平均压不动。
                results[i]['relevance'] = round((lib_sim * max(ts, 0.0)) ** 0.5, 3)
            else:
                results[i]['relevance'] = lib_sim
            nt = (metas[0].get('title') or '') if metas else ''
            results[i]['nearest'] = {'title': nt[:70], 'sim': lib_sim}
            # 精确层没抓到、但语义极像且标题也像 → 很可能是同一篇换了写法
            if results[i]['status'] == 'new' and lib_sim >= DUP_SIM:
                a, b = norm_title(papers[i].get('title')), norm_title(nt)
                if a and b and (a in b or b in a or _overlap(a, b) > 0.8):
                    results[i]['status'] = 'likely'
        except Exception:
            continue
    return results


def _cos(a, b):
    """余弦相似度。向量维度不一致或全零时返回 0，不抛异常。"""
    try:
        s = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(y * y for y in b) ** 0.5
        return s / (na * nb) if na and nb else 0.0
    except Exception:
        return 0.0


def _overlap(a, b):
    """粗略字符级重合度，用于「标题也像吗」的二次确认。"""
    if not a or not b:
        return 0.0
    sa, sb = set(a[i:i + 4] for i in range(len(a) - 3)), set(b[i:i + 4] for i in range(len(b) - 3))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def match(paper):
    """单篇对照。内部走 match_many，避免两套逻辑。"""
    return match_many([paper])[0]


def pick_seeds(topic, n=4):
    """从本地库里挑出与 topic 最相关的 n 篇，作为雪球的种子集。

    **为什么这一步是本平台独有的**：实证研究表明「雪球法的效果高度依赖种子集质量」。
    别人做雪球得先花力气构造种子集（或让用户手工指定）；
    我们有现成的 183 篇库 + 向量库，能自动挑出真正对口的几篇。
    这是结构性优势 —— 不是我们算法更好，是只有我们有这份数据。

    返回 [{'doi','title','sim'}]，Zotero/Ollama 不可用时返回空列表（调用方跳过雪球）。
    """
    coll = _collection()
    if coll is None:
        return []
    try:
        from shared.adapters.embed import embed as embed_batch
        qv = embed_batch([topic])[0]
        # 多取一些再按 DOI 去重 —— 向量库是按文本块存的，同一篇会命中多次
        hits = coll.query(qv, n=max(20, n * 6))
    except Exception:
        return []

    seen, seeds = set(), []
    for _h in hits:
        meta = _h['meta']
        doi = (meta.get('doi') or '').lower().strip()
        if not doi or doi in seen:
            continue
        seen.add(doi)
        seeds.append({'doi': doi, 'title': (meta.get('title') or '')[:70],
                      'sim': _h['sim']})      # 适配层已算好「越大越像」
        if len(seeds) >= n:
            break
    return seeds


def rank(papers, matches, w_rel=0.6, w_cite=0.25, w_fresh=0.15, year_now=None):
    """给候选文献排序：**与我的方向相关**为主，影响力与新鲜度为辅。

    默认权重刻意让相关度占大头（0.6）—— 因为高被引的通用综述对具体研究帮助有限，
    而正好做你那个体系的小众论文才是金子。库里已有的排最后（你已经有了）。

    返回按分数降序的 [(paper, match, score)]。
    """
    import datetime
    year_now = year_now or datetime.date.today().year
    rows = []
    for p, m in zip(papers, matches):
        rel = m.get('relevance')
        rel = 0.5 if rel is None else rel          # 语义不可用时给中性分，不惩罚
        c = p.get('citations') or 0
        cite = min(1.0, (c ** 0.5) / 20.0)         # 开方压缩：避免超高被引一家独大
        yr = p.get('year') or 0
        fresh = max(0.0, min(1.0, 1 - (year_now - yr) / 15.0)) if yr else 0.3
        score = w_rel * rel + w_cite * cite + w_fresh * fresh
        if m.get('status') in ('have', 'likely'):
            score -= 1.0                            # 已有的沉底，但仍列出供参考
        rows.append((p, m, round(score, 4)))
    rows.sort(key=lambda r: r[2], reverse=True)
    return rows
