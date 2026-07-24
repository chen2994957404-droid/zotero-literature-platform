# -*- coding: utf-8 -*-
"""向文献库提问（RAG）：从向量库检索相关内容，用DeepSeek结合内容回答。
用法: python ask.py "你的问题"
      python ask.py            进入交互模式，连续提问
"""
import os, json, sys, urllib.request
import chromadb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VECTOR_DB = os.path.join(ROOT, 'workflow_data', 'vector_db')
OLLAMA = 'http://localhost:11434/api/embed'
EMBED_MODEL = 'bge-m3'
DEEPSEEK_KEY = os.environ.get('DEEPSEEK_KEY', '***REMOVED***')
DEEPSEEK_MODEL = 'deepseek-v4-flash'
TOP_K = 6

client = chromadb.PersistentClient(path=VECTOR_DB)
coll = client.get_or_create_collection('literature', metadata={'hnsw:space': 'cosine'})

def embed(text):
    body = json.dumps({'model': EMBED_MODEL, 'input': text}).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())['embeddings'][0]

def deepseek(system, user):
    body = json.dumps({'model': DEEPSEEK_MODEL, 'temperature': 0.3,
        'messages': [{'role':'system','content':system},{'role':'user','content':user}]}, ensure_ascii=False).encode()
    req = urllib.request.Request('https://api.deepseek.com/chat/completions', data=body, method='POST',
        headers={'Authorization': f'Bearer {DEEPSEEK_KEY}', 'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=180).read())['choices'][0]['message']['content']

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
