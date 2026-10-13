# -*- coding: utf-8 -*-
"""deepread 的 MCP 面：一条提示词（人点，跑整篇）。

**这是全平台最贵的一条线**，所以模型不能自己发起，只能请人来点。
原来另有一个 `deepread_request`（= 在 Zotero 打「待处理」标签排队），2026-10-13 随 Zotero 移出平台删了；
日常单篇精读在文献库应用里点（有确认框、一篇一篇排队，花费上限由 `shared.kernel.budget` 兜着）。

本文件只做参数转换，一行业务逻辑都没有。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.kernel.mcp_prompt import card


def register(server):
    server.register_prompt(
        'deepread', '精读一篇文献：PDF → 中文图文报告（有 SI 就一并读并合并）。',
        [{'name': 'itemKey', 'description': '证据库里的文献 id（或 DOI 换成的 doi_… 编号）', 'required': True}],
        lambda a: card(
            f'精读文献 {a["itemKey"]}',
            cost='要花钱（MineRU 解析额度 + 大模型长文输出）',
            steps=[f'python -m tools.deepread {a["itemKey"]}'],
            notes='**更省事的办法：在文献库应用里打开这篇，点「精读这篇」**，一条命令都不用敲。\n'
                  '已精读过的部分不会重跑（省钱）：只有正文读过、后来补了 SI，就只补 SI 那段。\n'
                  '这条命令只在主力机上能跑（编程端会被机器角色守卫拦住）。\n'
                  '一篇要几分钟，会超过 MCP 的 60 秒上限 —— 后台发起后轮询产物文件，别干等。'))
