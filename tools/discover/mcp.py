# -*- coding: utf-8 -*-
"""discover 的 MCP 面：一条提示词（拆检索式花钱、导入写 Zotero → prompt）。

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
        'discover', '找新文献：拆检索式 + 引文雪球 + 按「跟我的库多相关」排序。',
        [{'name': 'query', 'description': '关键词，或一句话说清要解决什么问题', 'required': True},
         {'name': 'mode', 'description': 'survey=求全（默认）/ problem=求准（解决某个问题）',
          'required': False},
         {'name': 'since', 'description': '只要这一年之后的（如 2020）', 'required': False}],
        lambda a: card(
            f'找新文献：{a["query"]}',
            cost='要调用大模型拆检索式；走 Sciverse 那条路还需要密钥（--openalex 改用免费源）',
            steps=['python -m tools.discover "%s"%s%s' % (
                a['query'],
                ' --解决问题' if a.get('mode') == 'problem' else '',
                f' --since {a["since"]}' if a.get('since') else '')],
            notes='结果按「跟他多相关」排序，已在库的会标出来。\n'
                  '看完想收哪几篇：`python -m tools.discover.collect 1,3,5-7` —— '
                  '**这一步会写 Zotero，先把清单给用户看，等他说要哪几篇。**\n'
                  '入库后让用户在 Zotero 打「待处理」标签即自动精读。'))
