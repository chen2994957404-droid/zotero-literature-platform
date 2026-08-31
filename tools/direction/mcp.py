# -*- coding: utf-8 -*-
"""direction 的 MCP 面：一条提示词（建图很慢、brainstorm 花钱 → prompt）。

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
        'direction_map', '方向地图：一条窄带里谁做了什么、聚成哪些簇、空白在哪。',
        [{'name': 'band', 'description': '窄带名（如 impact）；不知道有哪些就先跑 bands',
          'required': True},
         {'name': 'step', 'description': 'stats（默认）/ bands / seeds / build / cluster / report',
          'required': False}],
        lambda a: card(
            '看 %s 这条窄带的方向地图（%s）' % (a['band'], a.get('step') or 'stats'),
            cost='seeds / build 要联网抓 OpenAlex，一次十几分钟；cluster / report 纯本地、免费',
            steps=['python -m tools.direction %s --band %s'
                   % (a.get('step') or 'stats', a['band'])],
            notes='一条新窄带的顺序：写 band.json → seeds → build → cluster → report。\n'
                  'cluster 与 report 不联网，可以反复调参数、反复看。\n'
                  '只是想「帮我想个 idea」→ `python -m tools.direction.brainstorm`（要大模型）。'))
