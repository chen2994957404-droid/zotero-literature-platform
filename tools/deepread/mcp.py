# -*- coding: utf-8 -*-
"""deepread 的 MCP 面：一条提示词（人点，跑整篇）+ 一个工具（排队，每次弹窗）。

**这是全平台最贵的一条线。** 但「模型绝不许自己发起」在 2026-09-10 被现实推翻了：
用户让外部 agent 精读一批，而 agent 在 MCP 上根本看不见本工具包（整包是 prompt），
于是它去读代码、自己打标签触发了 watcher —— 精读 10 篇，全程无人确认。

**堵不住就给正规入口。** 现在开的是 `deepread_request`＝**打「待处理」标签**：
快、幂等、可逆，真正花钱的活由常驻服务在后台干，而那一侧有
`shared.kernel.budget` 的当日额度闸兜着（那道闸不依赖客户端，
不像 MCP 的 confirm 换个客户端就失效）。

为什么不是「精读一篇」那种同步工具：一篇要跑几分钟，远超 MCP 约 60 秒的调用上限。

本文件只做参数转换，一行业务逻辑都没有。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel.mcp_prompt import card


def _request(a):
    """把一篇排进精读队列。**这里只做参数转换**，逻辑在 tools/deepread/request()。"""
    from tools import deepread
    key = (a.get('itemKey') or '').strip()
    if not key:
        return '要给 itemKey（Zotero 条目 key，8 位字母数字）。'
    r = deepread.request(key, log=lambda *x: None)
    words = {'queued': '排上了', 'already_queued': '本来就在队列里',
             'already_done': '已经精读过', 'failed': '没成'}
    head = f'{key} → {words.get(r["action"], r["action"])}'
    if r.get('state'):
        head += f'（当前状态标签：{r["state"]}）'
    return head + ('\n  ' + r['note'] if r.get('note') else '')


def register(server):
    server.register_tool(
        'deepread_request',
        '把**一篇**文献排进精读队列（= 在 Zotero 打「待处理」标签）。'
        '常驻服务会接手，跑出中文图文报告并挂回 Zotero，一篇几分钟。'
        '**会写用户的库，而且随后真的会花钱**，所以每次调用都要他确认。'
        '幂等：已在队列或已精读过都会如实告诉你，不会重复排。'
        '排完用 deepread_status 查进度，别干等。',
        {'type': 'object',
         'properties': {'itemKey': {'type': 'string',
                                    'description': 'Zotero 条目 key（8 位字母数字）'}},
         'required': ['itemKey']},
        _request,
        confirm=True)      # ← 写库且随后花钱，必须每次弹窗

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
