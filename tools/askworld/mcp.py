# -*- coding: utf-8 -*-
"""askworld 的 MCP 面：一条提示词（花钱 → 只能是 prompt，由人点）。

本文件只做参数转换，一行业务逻辑都没有。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel.mcp_prompt import card


def _ask(a):
    """问全世界一次。**只做参数转换**，逻辑在 tools/askworld/ask_world()。"""
    from tools import askworld
    q = (a.get('question') or '').strip()
    if not q:
        return {'text': '要给 question（要问的问题）。', 'structured': {'ok': False}}
    try:
        r = askworld.ask_world(q, top_k=int(a.get('top') or 8),
                               year_from=a.get('since'))
    except Exception as e:
        return {'text': f'没问成：{type(e).__name__}: {e}\n'
                        f'（需要 SCIVERSE_KEY；编程端通常没配，主力机上才有。）',
                'structured': {'ok': False}}
    if not r['evidence']:
        return {'text': f'没有找到足够相关的证据（检索式：{r["query_used"]}）。\n'
                        f'**这本身可能就是结论** —— 换个说法再问一次，'
                        f'或者用 lit_search 先看看这个词在全世界有多少篇。',
                'structured': {'ok': True, 'evidence': [], 'query_used': r['query_used']}}
    lines = [r['answer'], '', '证据（每条都可直接引用）：']
    for i, e in enumerate(r['evidence'], 1):
        page = f"，第{e['page']}页" if e.get('page') is not None else ''
        lines.append(f"  [{i}] 《{(e.get('title') or '')[:70]}》"
                     f"{e.get('year') or ''}{page}")
    return {'text': '\n'.join(lines),
            'structured': {'ok': True, 'answer': r['answer'],
                           'evidence': r['evidence'], 'query_used': r['query_used']}}


def register(server):
    server.register_tool(
        'askworld_ask',
        '问全世界一个科学问题：从 Sciverse 全文库取**原文片段**作答，'
        '每条结论都带出处（标题/年份/页码），可直接引用。**要花钱**（Sciverse + 大模型），'
        '所以每次调用都要用户确认。只读，不写任何东西，可重来。'
        '问的是用户**自己库里**的东西 → 用 ask_library；'
        '只想要一份该读的清单 → 用 lit_search。',
        {'type': 'object', 'properties': {
            'question': {'type': 'string', 'description': '要问的问题（中文英文都行）'},
            'since': {'type': 'integer', 'description': '只要这一年之后的文献'},
            'top': {'type': 'integer', 'minimum': 1, 'maximum': 20,
                    'description': '取几条证据，默认 8'}},
         'required': ['question']},
        _ask,
        confirm=True)      # ← 花钱，必须每次弹窗

    server.register_prompt(
        'askworld', '问全世界：从 Sciverse 全文库取原文片段，带出处地回答一个科学问题。',
        [{'name': 'question', 'description': '要问的问题', 'required': True},
         {'name': 'since', 'description': '只要这一年之后的文献（如 2020）', 'required': False},
         {'name': 'top', 'description': '取几条证据（默认 8）', 'required': False}],
        lambda a: card(
            f'问全世界：{a["question"]}',
            cost='要调用 Sciverse 检索 + 付费大模型，且需要 SCIVERSE_KEY',
            steps=['python -m tools.askworld "%s"%s%s' % (
                a['question'],
                f' --since {a["since"]}' if a.get('since') else '',
                f' --top {a["top"]}' if a.get('top') else '')],
            notes='答案里每条结论都带出处（标题/年份/期刊/被引/页码），可直接引用。\n'
                  '问的是**我自己库里**的文献 → 换 ask；只想要一份检索列表 → 换 discover。'))
