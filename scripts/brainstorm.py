# -*- coding: utf-8 -*-
"""创意讨论工具：结合你的文献库，和大模型讨论方向、找空白、提idea。
与 ask.py 的区别：ask.py 做事实检索问答；这个做创意发散讨论。
用法: python brainstorm.py "我想在自修复材料方向找新点子"
      python brainstorm.py            进入连续讨论模式
"""
import os, json, sys, urllib.request
import chromadb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VECTOR_DB = os.path.join(ROOT, 'workflow_data', 'vector_db')
DEEPSEEK_KEY = os.environ.get('DEEPSEEK_KEY', '***REMOVED***')
# 创意讨论用 pro（质量更重要），可改 flash
CHAT_MODEL = os.environ.get('BRAINSTORM_MODEL', 'deepseek-v4-pro')
TOP_K = 10  # 讨论要更多上下文

# embedding 走公理件（chat 是多轮 messages 形式，接口不同，暂保留原实现，见技术债）
sys.path.insert(0, ROOT)
from modules.embed import embed as _embed_batch

client = chromadb.PersistentClient(path=VECTOR_DB)
coll = client.get_or_create_collection('literature', metadata={'hnsw:space': 'cosine'})

def embed(text):
    return _embed_batch([text])[0]

def chat(messages):
    body = json.dumps({'model': CHAT_MODEL, 'temperature': 0.7,  # 创意用高温度
        'max_tokens': 4000, 'messages': messages}, ensure_ascii=False).encode()
    req = urllib.request.Request('https://api.deepseek.com/chat/completions', data=body, method='POST',
        headers={'Authorization': f'Bearer {DEEPSEEK_KEY}', 'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=200).read())['choices'][0]['message']['content']

SYSTEM = """你是一位资深科研导师，正在和一位研究生讨论研究方向、激发新想法。
你会拿到「用户想探讨的方向」和「从他自己文献库检索出的相关文献片段」。
你的任务不是简单总结文献，而是像真正的科研头脑风暴那样：
1. 先快速梳理这些文献里已有的思路和方法（让讨论有据可依）；
2. 找出其中的空白、矛盾、或可以迁移组合的地方；
3. 大胆提出几个具体、可操作的新想法或研究方向，说明灵感来自哪几篇文献的什么点；
4. 指出每个想法可能的难点和验证思路。
用中文，专业、有启发性、敢于发散。基于文献但不局限于文献。"""

def retrieve(query, k=TOP_K):
    qvec = embed(query)
    res = coll.query(query_embeddings=[qvec], n_results=k, include=['documents', 'metadatas'])
    return res['documents'][0], res['metadatas'][0]

def build_context(docs, metas):
    ctx = ''
    srcs = {}
    for i, (doc, m) in enumerate(zip(docs, metas)):
        ctx += f'\n【文献片段{i+1}·《{m["title"][:45]}》】\n{doc}\n'
        srcs[m['title'][:50]] = m.get('doi', '')
    return ctx, srcs

def main():
    print(f'💡 创意讨论模式（基于你的 {coll.count()} 块文献 · {CHAT_MODEL}）')
    history = [{'role': 'system', 'content': SYSTEM}]
    first = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else None

    def turn(user_input):
        # 每轮都用当前输入检索最新相关文献
        docs, metas = retrieve(user_input)
        ctx, srcs = build_context(docs, metas)
        history.append({'role': 'user',
            'content': f'我想探讨的方向：{user_input}\n\n从我的文献库检索到的相关内容：\n{ctx}'})
        ans = chat(history)
        history.append({'role': 'assistant', 'content': ans})
        print('\n' + '='*55)
        print(ans)
        print('='*55)
        print('\n📚 本轮参考的文献：')
        for t, d in list(srcs.items())[:6]:
            print(f'  - 《{t}》' + (f'  {d}' if d else ''))

    if first:
        turn(first)
        # 命令行单次后也可继续
    print('\n（继续追问输入内容，回车提交；输入 q 退出）')
    while True:
        try:
            u = input('\n你> ').strip()
        except EOFError:
            break
        if u.lower() in ('q', 'quit', 'exit', ''):
            break
        try:
            turn(u)
        except Exception as e:
            print('出错：', e)

if __name__ == '__main__':
    main()
