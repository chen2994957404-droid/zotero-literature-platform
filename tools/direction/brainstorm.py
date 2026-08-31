# -*- coding: utf-8 -*-
"""创意讨论：结合你的文献库，和大模型讨论方向、找空白、提 idea。

与 `tools/ask` 的区别：ask 做**事实检索问答**（只许照片段说话）；
这里做**创意发散讨论**（基于文献但允许跳出去），所以温度高、用 pro 模型、多轮带上下文。

用法: python -m tools.direction.brainstorm "我想在自修复材料方向找新点子"
      python -m tools.direction.brainstorm            进入连续讨论模式
"""
import os, sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from shared.kernel import paths, prompts

from shared.adapters import vectordb
from shared.adapters.embed import embed as _embed_batch
from shared.adapters.llm_client import chat_messages
from shared.kernel.cli import positionals
from shared.kernel.config import get_key, get_model

VECTOR_DB = paths.VECTOR_DB
DEEPSEEK_KEY = get_key('DEEPSEEK_KEY')
# 创意讨论用 pro（质量更重要）；模型名统一走 config，控制面板可切换
CHAT_MODEL = get_model('BRAINSTORM_MODEL')
TOP_K = 10  # 讨论要更多上下文


def embed(text):
    return _embed_batch([text])[0]


def chat(messages):
    """多轮讨论走适配层（红线 #5：联网只在 adapters）。温度 0.7 —— 创意要发散。"""
    return chat_messages(messages, provider='deepseek', model=CHAT_MODEL,
                         key=DEEPSEEK_KEY, temperature=0.7, max_tokens=4000)


SYSTEM = prompts.load('direction', 'brainstorm@v1')


def retrieve(coll, query, k=TOP_K):
    qvec = embed(query)
    hits = coll.query(qvec, n=k)
    return [h['doc'] for h in hits], [h['meta'] for h in hits]


def build_context(docs, metas):
    ctx = ''
    srcs = {}
    for i, (doc, m) in enumerate(zip(docs, metas)):
        ctx += f'\n【文献片段{i+1}·《{m["title"][:45]}》】\n{doc}\n'
        srcs[m['title'][:50]] = m.get('doi', '')
    return ctx, srcs


def main():
    coll = vectordb.open_store()
    print(f'💡 创意讨论模式（基于你的 {coll.count()} 块文献 · {CHAT_MODEL}）')
    history = [{'role': 'system', 'content': SYSTEM}]
    rest = positionals()
    first = ' '.join(rest) if rest else None

    def turn(user_input):
        # 每轮都用当前输入检索最新相关文献
        docs, metas = retrieve(coll, user_input)
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
