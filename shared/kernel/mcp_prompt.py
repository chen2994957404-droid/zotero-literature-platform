# -*- coding: utf-8 -*-
"""mcp_prompt · 把「花钱/有副作用的能力」拼成一段给模型看的话。

为什么需要它：平台九成的能力都花钱或写 Zotero，这些**不能让模型自己调**
（见 REBUILD.md R4 判据），所以它们在 MCP 上是 prompt —— 用户在客户端里点一下，
客户端把这段话喂给模型，模型再照着办。

那段话每次都要说同样三件事：**代价是什么、先问用户、然后跑哪条命令**。
八个工具各抄一遍就会各说各话，说漏「先问用户」那句的那个工具就是事故。
所以统一在这里拼。

用法：
    from shared.kernel.mcp_prompt import card
    card('精读文献 ABCD1234',
         cost='会调用付费大模型，并把结果写回 Zotero',
         steps=['python -m tools.deepread ABCD1234'],
         notes='报告在 library/ABCD1234/summary.html。')
"""


def card(what, cost, steps, notes=''):
    """拼一段提示词。what=要做什么，cost=代价，steps=命令列表，notes=补充说明。"""
    lines = [f'用户想{what}。', '']
    if cost:
        lines += [f'⚠ 这件事{cost}。**先把要做的事和代价用大白话讲给用户听，'
                  f'等他明确点头再动手。**', '']
    lines.append('照这样做：')
    lines += [f'    {s}' for s in steps]
    if notes:
        lines += ['', notes]
    lines += ['', '（用户不懂编程：别贴 traceback，用大白话汇报结果。）']
    return '\n'.join(lines)
