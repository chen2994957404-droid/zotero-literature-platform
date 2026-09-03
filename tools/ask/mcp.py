# -*- coding: utf-8 -*-
"""ask 的 MCP 面：一个**带强制确认的 tool** + 一条给全库向量化用的 prompt。

## 为什么这里能是 tool（2026-09-01 改）

原来的规则是「花钱的一律做成 prompt」。那条规则把「问一次库（几分钱、可重来）」
和「全库向量化（全库作业）」当成了同一件事 —— 代价差两三个数量级。

现在按**代价量级 + 可不可逆**分档：问一次库是单次、便宜、无副作用（不写任何东西），
所以做成 tool，但打上 `anthropic/requiresUserInteraction` ——
Claude Code 每次调用都会弹窗让你点头，**而且不给「不再询问」的选项**。

全库向量化仍然是 prompt（人点）：那是全库作业，不该由模型发起。

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
    """问一次库 → 给模型看的文本（答案 + 来源）。"""
    from tools import ask as A
    r = A.ask_answer(a['question'])
    if not r['chunks']:
        return ('向量库是空的，一个片段都没检索到。\n'
                '先在主力机上跑一次全库向量化：python -m tools.ask.vectorize')
    lines = [r['answer'], '', '📚 来源：']
    for s in r['sources']:
        lines.append(f'  - 《{s["title"]}》' + (f'  DOI:{s["doi"]}' if s['doi'] else ''))
    lines.append('')
    lines.append(f'（基于 {r["chunks"]} 个片段作答。**答案之外的话别替它补**——'
                 f'没检索到就是库里没有。）')
    return '\n'.join(lines)


def register(server):
    server.register_tool(
        'ask_library',
        '问用户自己的 Zotero 文献库（检索向量库 + 大模型中文作答，附来源）。'
        '**要花钱**：一次几分钱，调用时会先弹窗让用户确认。'
        '只想知道某篇在不在库里，用 library_search 更便宜。',
        {'type': 'object',
         'properties': {'question': {'type': 'string', 'description': '要问的问题（中文即可）'}},
         'required': ['question']},
        _ask,
        confirm=True)      # ← 每次都弹窗，且没有「不再询问」

    server.register_prompt(
        'ask_vectorize', '把新文献并进问答用的向量库（全库作业，只在主力机跑）。',
        [],
        lambda a: card(
            '把新文献并进问答向量库',
            cost='是**全库作业**：要遍历整个库、逐块调本地向量化模型，跑很久',
            steps=['python -m tools.ask.vectorize'],
            notes='平时不用手动跑 —— `host/autosync` 每小时会自动增量做一次。\n'
                  '只有在「刚导入一大批文献、又等不及下一次自动同步」时才需要。\n'
                  '这条只在主力机上能跑（编程端会被机器角色守卫拦住）。'))
