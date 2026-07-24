# -*- coding: utf-8 -*-
"""向文献库提问（RAG）：从向量库检索相关内容，用DeepSeek结合内容回答。
用法: python ask.py "你的问题"
      python ask.py            进入交互模式，连续提问
"""
import os, json, sys, urllib.request
import chromadb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VECTOR_DB = os.path.join(ROOT, 'workflow_data', 'vector_db')
DEEPSEEK_KEY = os.environ.get('DEEPSEEK_KEY', '***REMOVED***')
DEEPSEEK_MODEL = 'deepseek-v4-flash'   # 问答输出较长，用 flash 省钱
TOP_K = 6

# embedding 与 LLM 调用走公理件
sys.path.insert(0, ROOT)
from modules.embed import embed as _embed_batch
from modules.llm_client import chat as _chat

client = chromadb.PersistentClient(path=VECTOR_DB)
coll = client.get_or_create_collection('literature', metadata={'hnsw:space': 'cosine'})

def embed(text):
    return _embed_batch([text])[0]   # 公理件是批量接口，取第一个

def deepseek(system, user):
    return _chat(system, user, provider='deepseek', model=DEEPSEEK_MODEL, key=DEEPSEEK_KEY, temperature=0.3)

def ask(question):
    # 1. 问题向量化，检索相关块
    qvec = embed(question)
    res = coll.query(query_embeddings=[qvec], n_results=TOP_K, include=['documents','metadatas','distances'])
    docs = res['documents'][0]
    metas = res['metadatas'][0]
    if not docs:
        print('向量库是空的，先跑 vectorize.py'); return
    # 2. 组装上下文
    context = ''
    sources = {}
    for i, (doc, m) in enumerate(zip(docs, metas)):
        context += f'\n【片段{i+1}·来自《{m["title"][:40]}》】\n{doc}\n'
        sources[m['title'][:50]] = m.get('doi', '')
    # 3. DeepSeek 结合内容回答
    system = ('你是科研文献助手。请只根据下面提供的文献片段回答用户问题，用中文，准确专业。'
              '如果片段里没有相关信息，就说明文献库里没有找到。回答末尾不用列来源，我会另外附上。')
    user = f'文献片段：\n{context}\n\n用户问题：{question}'
    answer = deepseek(system, user)
    print('\n' + '='*50)
    print(answer)
    print('='*50)
    print('\n📚 参考来源：')
    for t, doi in sources.items():
        print(f'  - 《{t}》' + (f'  DOI:{doi}' if doi else ''))
    print()

if __name__ == '__main__':
    print(f'向量库共 {coll.count()} 个文本块\n')
    if len(sys.argv) > 1:
        ask(' '.join(sys.argv[1:]))
    else:
        print('进入问答模式（输入问题，回车提问；输入 q 退出）')
        while True:
            q = input('\n问> ').strip()
            if q.lower() in ('q', 'quit', 'exit', ''):
                break
            try:
                ask(q)
            except Exception as e:
                print('出错：', e)
