# -*- coding: utf-8 -*-
"""ask · 库内问答：向**我自己的**文献库提问，中文作答并附来源。

「我库里关于 XX 有什么」——从向量库检索相关片段，交给大模型结合片段回答。
**答案只允许基于检索到的片段**，这是「可追溯」的前提；模型不许自由发挥。

与 `tools/askworld`（问全世界）的分工：
    ask       → 问**我读过的**（本地向量库，答得深，免费）
    askworld  → 问**全世界**（Sciverse 三千万篇全文，答得广，要密钥）

**对外契约**（别的地方只许调这些；`cli.py` / `mcp.py` 也只许调这些）：

| 入口 | 干什么 |
|---|---|
| `ask_answer(question, top_k)` | **主入口**：检索 + 作答，返回结构化结果（不打印）|
| `ask(question)`               | 命令行用：调 `ask_answer` 并打印答案与来源 |
| `count()`                     | 向量库里现在有多少块 |
| `vectorize.deep_all()`        | 精层向量化：精读过的 `parsed/full.md` → 向量库 |
| `vectorize.light_all()`       | 粗层向量化：Zotero 全文索引 → 向量库（广撒网）|

**向量化为什么算在问答工具里**：它是问答的前置，不是独立能力 ——
没有向量库，问答只能回答「库是空的」。两者一起改、一起测才不会脱节。

它组合了什么：
    shared.kernel.paths（向量库在哪） + shared.adapters.embed（文本→向量）
  + shared.adapters.vectordb（存/查，换向量库只改那一块）
  + shared.adapters.llm_client（谁来作答）

`ask_answer` **返回**而不是打印 —— 面板、MCP、命令行共用同一份逻辑。
"""
import os
import sys

from shared.adapters import vectordb
from shared.adapters.embed import embed as _embed_batch
from shared.adapters.llm_client import chat as _chat
from shared.kernel import paths, prompts
from shared.kernel.config import get_key, get_model

VECTOR_DB = paths.VECTOR_DB
TOP_K = 6

SYS = prompts.load('ask', 'main@v1')


def _store():
    """打开向量库。换哪家向量库只改 shared/adapters/vectordb。"""
    return vectordb.open_store()


def count():
    """向量库里现在有多少个文本块（面板与命令行都要显示这个数）。"""
    try:
        return _store().count()
    except Exception:
        return 0


def embed(text):
    """单条文本 → 向量（适配层是批量接口，取第一个）。"""
    return _embed_batch([text])[0]


def answer_with(system, user):
    """调云端 DeepSeek 作答（问答输出较长，用 flash 省钱；模型可在控制面板切换）。"""
    return _chat(system, user, provider='deepseek', model=get_model('ASK_MODEL'),
                 key=get_key('DEEPSEEK_KEY'), temperature=0.3)


def ask_answer(question, top_k=TOP_K):
    """RAG 问答，**返回**结果而不是打印 —— 供 MCP / 面板 / 其他脚本复用。

    返回 {'answer': str, 'sources': [{'title','doi','si'}], 'chunks': int}
    `si=True` 表示这篇的**补充材料**被引用了 —— 必须让用户看见，
    否则他拿着出处去正文里找会找不到（SI 是另一个文件）。
    找不到内容时 answer 为空串、chunks 为 0（调用方据此给提示）。
    """
    hits = _store().query(embed(question), n=top_k)
    docs = [h['doc'] for h in hits]
    metas = [h['meta'] for h in hits]
    if not docs:
        return {'answer': '', 'sources': [], 'chunks': 0}
    context = ''
    sources = {}
    si_titles = set()   # 哪些文献这次用到了 SI —— 出处要标出来，否则用户去正文里找会找不到
    for i, (doc, m) in enumerate(zip(docs, metas)):
        # 没有 source 字段的是早期入库的块，一律当正文（向后兼容旧库）
        where = '补充材料SI' if m.get('source') == 'si' else '正文'
        context += f'\n【片段{i+1}·来自《{m["title"][:40]}》的{where}】\n{doc}\n'
        t = m['title'][:50]
        sources[t] = m.get('doi', '')
        if m.get('source') == 'si':
            si_titles.add(t)
    answer = answer_with(SYS, f'文献片段：\n{context}\n\n用户问题：{question}')
    return {'answer': answer,
            'sources': [{'title': t, 'doi': d, 'si': t in si_titles}
                        for t, d in sources.items()],
            'chunks': len(docs)}


def ask(question, top_k=TOP_K):
    """命令行用：调 ask_answer 并打印答案与来源。"""
    r = ask_answer(question, top_k=top_k)
    if not r['chunks']:
        print('向量库是空的，先跑：python -m tools.ask.vectorize')
        return r
    print('\n' + '=' * 50)
    print(r['answer'])
    print('=' * 50)
    print('\n📚 参考来源：')
    for s in r['sources']:
        print(f'  - 《{s["title"]}》'
              + ('（含补充材料 SI）' if s.get('si') else '')
              + (f'  DOI:{s["doi"]}' if s['doi'] else ''))
    print()
    return r
