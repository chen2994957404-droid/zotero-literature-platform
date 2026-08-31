# -*- coding: utf-8 -*-
"""askworld · 问全世界：向全球文献提一个科学问题，拿到**带原文出处**的中文回答。

与 `tools/ask`（问我的库）的分工（互补，不重叠）：
    ask       → 问**我读过的**（本地向量库，38 篇精读，答得深，免费）
    askworld  → 问**全世界**（Sciverse 三千万篇全文，答得广，要密钥）

流程：中文问题 → 转英文检索式 → Sciverse 取回可引用的原文片段 →
DeepSeek 结合片段用中文作答 → 附出处。
**答案只允许基于取回的片段**，不许模型自由发挥 —— 这是「可追溯」的前提。

**对外契约**（别的地方只许调这些；`cli.py` / `mcp.py` 也只许调这些）：

| 入口 | 干什么 |
|---|---|
| `ask_world(question, top_k, year_from)` | **主入口**：检索证据 + 作答，返回结构化结果 |
| `search_world(query, limit, ...)`       | 只检索不作答：全球文献列表 + 标出库里已有 |
| `available()`                           | 有没有配 Sciverse 密钥（没配就别提示用户去用）|

**为什么必须先转英文**（踩坑 #35 实测，不是设计洁癖）：
Sciverse 按提问语言给同语言文献加权。中文问「聚硼硅氧烷的剪切硬化机理」
召回的是硼硅玻璃辐照、炉渣、LTCC 陶瓷；同一问题用英文问，相关度 0.97 且全部对口。

它组合了什么：
    shared.adapters.query_expand（中文 → 英文检索式）
  + shared.adapters.sciverse（谁来检索，唯一联网的一环）
  + shared.adapters.llm_client（谁来作答）
  + shared.adapters.zotero_client（这篇我有没有）
"""
import re

from shared.adapters.llm_client import chat
from shared.adapters.query_expand import to_english
from shared.adapters.sciverse import (SciverseError, ask_evidence, available,
                                      looks_chinese, search_papers)
from shared.adapters.zotero_client import library_index
from shared.kernel.config import get_key, get_model

SYS = ('你是科研文献助手。请**只根据下面提供的文献片段**回答用户问题，用中文，准确专业。'
       '每个关键论断后面用 [1] [2] 这样的编号标出依据来自哪条片段。'
       '如果片段里没有足够信息，就直说「提供的文献片段中没有找到相关证据」，'
       '**不要用你自己的知识补充**——本工具的价值在于可追溯。'
       '回答末尾不用列来源，程序会另外附上。')

MIN_SCORE = 0.60      # 相关度低于此值的片段基本是噪声，实测 0.35~0.5 的全是跑题的


def norm_title(t):
    """标题归一：去标点、空白、大小写。用于「这篇我有没有」比对。"""
    return re.sub(r'[^a-z0-9]', '', (t or '').lower())


def ask_world(question, top_k=8, year_from=None, min_score=MIN_SCORE):
    """向全球文献提问。返回 {'answer','evidence','query_used'}。

    找不到足够相关的证据时 answer 为空串、evidence 为空（调用方据此给提示）——
    **宁可少给几条，也不要拿跑题片段污染答案**。
    """
    q_en = to_english(question)
    ev = ask_evidence(q_en, top_k=max(top_k, 12), year_from=year_from)
    ev = [e for e in ev if e['score'] >= min_score][:top_k]
    if not ev:
        return {'answer': '', 'evidence': [], 'query_used': q_en}
    ctx = ''
    for i, e in enumerate(ev, 1):
        page = f"，第{e['page']}页" if e.get('page') is not None else ''
        ctx += (f"\n【片段{i}·《{e['title'][:60]}》{e['year'] or ''}{page}】\n"
                f"{e['chunk'][:1200]}\n")
    answer = chat(SYS, f'文献片段：\n{ctx}\n\n用户问题：{question}',
                  provider='deepseek', model=get_model('ASK_MODEL'),
                  key=get_key('DEEPSEEK_KEY'), temperature=0.3,
                  max_tokens=8000, thinking=False)
    return {'answer': answer, 'evidence': ev, 'query_used': q_en}


def search_world(query, limit=20, year_from=None, prefer='relevance'):
    """只检索不作答：全球文献列表，并标出哪些库里已经有了。

    返回 {'items': [...], 'total': int}，每条多一个 `in_library` 字段。
    prefer ∈ relevance / citations / impact / fresh。
    """
    r = search_papers(query, limit=limit, year_from=year_from, prefer=prefer)
    titles, dois = library_index()
    for it in r['items']:
        it['in_library'] = ((it.get('doi') or '').lower() in dois
                            or norm_title(it.get('title')) in titles)
    return r
