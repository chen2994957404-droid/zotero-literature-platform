# -*- coding: utf-8 -*-
"""curate 的 MCP 面：一条提示词（写 Zotero → 只能是 prompt，由人点）。

库房维护会**改用户真实的文献库**，模型绝不许自己发起。本文件只做参数转换。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel.mcp_prompt import card

WHAT = {
    'sync': '跑一次增量同步（向量化 + 粗层抽取）',
    'junk': '找出没有正文 PDF 的垃圾条目',
    'rename': '把附件名统一成 Full Text PDF / SI / Snapshot',
    'backfill': '给缺 meta.json 的文献补元数据',
    'tags': '把 dim:value 标签改成 dim/value 的嵌套写法',
}


def register(server):
    server.register_prompt(
        'curate', '库房维护：定时同步 / 清垃圾条目 / 附件改名 / 补元数据 / 标签改造。',
        [{'name': 'action', 'description': 'sync | junk | rename | backfill | tags',
          'required': True}],
        lambda a: card(
            WHAT.get(a['action'], a['action']),
            cost='会**写用户真实的 Zotero 库**（sync 还会顺带跑全库作业）',
            steps=[f'python -m tools.curate {a["action"]}'],
            notes='junk / rename / tags 都是**先预览后执行**：不带 `--删除` / `apply` 只列清单。\n'
                  '**一定先把清单给用户看，等他明确说删哪些、改哪些，再执行。**\n'
                  '这些命令只在主力机上能跑（编程端会被机器角色守卫拦住）。'))
