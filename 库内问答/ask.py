# -*- coding: utf-8 -*-
"""向文献库提问（RAG）：从向量库检索相关内容，用DeepSeek结合内容回答。
用法: python ask.py "你的问题"
      python ask.py            进入交互模式，连续提问
"""
import os, sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from core import paths

from core.cli import positionals
from core.config import get_key, get_model
from adapters.embed import embed as _embed_batch
from adapters.llm_client import chat as _chat
from adapters import vectordb

VECTOR_DB = paths.VECTOR_DB
DEEPSEEK_KEY = get_key('DEEPSEEK_KEY')
DEEPSEEK_MODEL = get_model('ASK_MODEL')      # 可在控制面板切换
TOP_K = 6

# embedding 与 LLM 调用走公理件
coll = vectordb.open_store()          # 向量库走适配层，换库只改 adapters/vectordb


def embed(text):
    """单条文本 → 向量（公理件是批量接口，取第一个）。"""
    return _embed_batch([text])[0]


def deepseek(system, user):
    """调云端 DeepSeek 作答（问答输出较长，用 flash 省钱）。"""
    return _chat(system, user, provider='deepseek', model=DEEPSEEK_MODEL, key=DEEPSEEK_KEY, temperature=0.3)


def ask_answer(question, top_k=TOP_K):
    """RAG 问答，**返回**结果而不是打印 —— 供 MCP / 其他脚本复用。

    返回 {'answer': str, 'sources': [{'title','doi'}], 'chunks': int}
    找不到内容时 answer 为空串、chunks 为 0（调用方据此给提示）。
    """
    qvec = embed(question)
    hits = coll.query(qvec, n=top_k)
    docs = [h['doc'] for h in hits]
    metas = [h['meta'] for h in hits]
    if not docs:
        return {'answer': '', 'sources': [], 'chunks': 0}
    context = ''
    sources = {}
    for i, (doc, m) in enumerate(zip(docs, metas)):
        context += f'\n【片段{i+1}·来自《{m["title"][:40]}》】\n{doc}\n'
        sources[m['title'][:50]] = m.get('doi', '')
    system = ('你是科研文献助手。请只根据下面提供的文献片段回答用户问题，用中文，准确专业。'
              '如果片段里没有相关信息，就说明文献库里没有找到。回答末尾不用列来源，我会另外附上。')
    answer = deepseek(system, f'文献片段：\n{context}\n\n用户问题：{question}')
    return {'answer': answer,
            'sources': [{'title': t, 'doi': d} for t, d in sources.items()],
            'chunks': len(docs)}


def ask(question):
    """命令行用：调 ask_answer 并打印。"""
    r = ask_answer(question)
    if not r['chunks']:
        print('向量库是空的，先跑 vectorize.py'); return
    answer = r['answer']
    sources = {s['title']: s['doi'] for s in r['sources']}
    print('\n' + '='*50)
    print(answer)
    print('='*50)
    print('\n📚 参考来源：')
    for t, doi in sources.items():
        print(f'  - 《{t}》' + (f'  DOI:{doi}' if doi else ''))
    print()


def main():
    """命令行入口：有参数直接提问，无参数进交互模式。"""
    print(f'向量库共 {coll.count()} 个文本块\n')
    args = positionals()
    if args:
        ask(' '.join(args))
    else:
        print('进入问答模式（输入问题，回车提问；输入 q 退出）')
        while True:
            q = input('\n问> ').strip()
            if q.lower() in ('q', 'quit', 'exit', ''):
                break
            try:
                ask(q)
            except Exception as e:
                # 单条问题失败只提示不退出：交互模式下用户可继续问下一条
                print('出错：', e)


if __name__ == '__main__':
    main()
