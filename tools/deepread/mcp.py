# -*- coding: utf-8 -*-
"""deepread 的 MCP 面：一条提示词（花钱 + 写 Zotero → 只能是 prompt）。

**这是全平台最贵的一条线**，模型绝不许自己发起。本文件只做参数转换。
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
        'deepread', '精读一篇文献：PDF → 中文图文报告（有 SI 就一并读并合并），回写 Zotero。',
        [{'name': 'itemKey', 'description': 'Zotero 条目 key（8 位字母数字）', 'required': True}],
        lambda a: card(
            f'精读文献 {a["itemKey"]}',
            cost='要花钱（MineRU 解析额度 + 付费大模型长文输出），并且会把报告写回 Zotero',
            steps=[f'python -m tools.deepread {a["itemKey"]}'],
            notes='**更省事的办法：让用户自己在 Zotero 里打「待处理」标签**，'
                  'watcher 会自动精读，一条命令都不用敲。\n'
                  '已精读过的部分不会重跑（省钱）：只有正文读过、后来补了 SI，就只补 SI 那段。\n'
                  '这条命令只在主力机上能跑（编程端会被机器角色守卫拦住）。\n'
                  '一篇要几分钟，会超过 MCP 的 60 秒上限 —— 后台发起后轮询产物文件，别干等。'))
