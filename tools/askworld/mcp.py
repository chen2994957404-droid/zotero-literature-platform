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


def register(server):
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
