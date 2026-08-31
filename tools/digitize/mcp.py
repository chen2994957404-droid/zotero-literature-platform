# -*- coding: utf-8 -*-
"""digitize 的 MCP 面：一条提示词（要云端视觉大模型 → 花钱 → prompt）。

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
        'digitize', '把论文图里的曲线/散点/柱状图读成 X-Y 数值。',
        [{'name': 'imagePath', 'description': '图片文件路径', 'required': True},
         {'name': 'hint', 'description': '额外提示，如「只读红色那条曲线」', 'required': False}],
        lambda a: card(
            f'把图 {a["imagePath"]} 里的曲线读成数值',
            cost='要调用云端视觉大模型',
            steps=['python -m tools.digitize "%s"%s' % (
                a['imagePath'],
                ' --hint "%s"' % a['hint'] if a.get('hint') else '')],
            notes='⚠ **别为了省钱换本地 7B**：它会编出看似合理的假数据还标高置信度'
                  '（实测把 FTIR 光谱读成完美等差数列）。编的数字最像事实。\n'
                  '要先从 PDF 里把图裁出来，用 `shared.domain.figure_crop`。'))
