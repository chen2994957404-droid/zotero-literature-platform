# -*- coding: utf-8 -*-
"""ask 的 MCP 面：一条提示词（**由人点，不是模型自己调**）。

为什么不是 tool：问一次要调付费大模型。按 R4 判据，花钱的能力一律做成 prompt ——
用户在客户端里点一下，模型才照着做。`host/mcp/registry.py` 的 check() 会强制这条。

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
        'ask', '问我自己的文献库（检索向量库 + 大模型中文作答，附来源）。',
        [{'name': 'question', 'description': '要问的问题（中文即可）', 'required': True}],
        lambda a: card(
            f'问自己的文献库：{a["question"]}',
            cost='要调用付费大模型（一次几分钱）',
            steps=[f'python -m tools.ask "{a["question"]}"'],
            notes='答案**只允许基于检索到的片段**，末尾会附来源；库里没有就会直说没有。\n'
                  '若提示向量库是空的，先跑 `python -m tools.ask.vectorize`'
                  '（全库作业，只在主力机跑）。\n'
                  '问的是全世界而不是自己的库 → 换 askworld。'))
