# -*- coding: utf-8 -*-
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass
"""library 的 MCP 面：只读工具（模型可以自己调，不花钱、不写东西）。

**本文件只做参数转换**：把 MCP 传来的 arguments 拆成 Python 参数、把返回值
渲染成文本。一行业务逻辑都不许写在这里 —— 逻辑在 `tools/library/__init__.py`，
那样命令行、面板、MCP 三个入口共用同一份行为，不会各说各话。

2026-10-13 Zotero 移出平台：原来查 Zotero 的 9 个工具（stats / search / item / pdf / fulltext / 合集 / 标签 / 最近）删了。
"""
from tools import library

_KEY = {'itemKey': {'type': 'string',
                    'description': '文献 id（由 DOI 生成的 doi_… 为主；旧的 8 位编号也认），'
                                   '也可以直接给 DOI（10.xxxx/...），会先在证据库里对账'}}


def _k(a):
    """把 itemKey 参数解析成证据库 id：给的是 DOI 就按 DOI 对账（外部 agent 手里常常只有 DOI，
    2026-09-19 Antigravity 实测传 DOI 被拒）。对不上就原样返回，让下游报「没这篇」。"""
    from shared.kernel import catalog
    k = (a.get('itemKey') or '').strip()
    if k.startswith('10.') and '/' in k:
        pid = catalog.find(k)
        if not pid:
            raise ValueError(f'证据库里没有 DOI {k} 这篇（先用 library_db_search 确认，或用 paper_fulltext 把它拿进来）')
        return pid
    return k


def register(server):
    """把本工具的 MCP 面挂到 server 上（聚合入口 host/mcp/server.py 会调这个）。"""

    # ── 证据库（全集）：先问这里，零网络 ───────────────────────────
    server.register_tool(
        'library_db_search',
        '搜**证据库**（平台自己的库）：'
        '按标题 / DOI / 期刊 子串，返回每篇的 id 和手上有什么（正文/SI/已解析）。'
        '不联网、秒回。**问「有没有这篇」先用它**。',
        {'type': 'object', 'properties': {
            'query': {'type': 'string', 'description': '标题片段、DOI 或期刊名'},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}},
         'required': ['query']},
        lambda a: library.render_db(library.db_search(a.get('query'), limit=a.get('limit', 25))))

    server.register_tool(
        'library_retrieve',
        '在证据库里**找哪里讲了 X**：向量检索，返回最相近的几段原文 + 文献 id + 骨架地址'
        '（s5.p3 这种）。零成本、不过大模型、不替你判断 —— 这是「搜库 → 点节 → 读」的第一步。',
        {'type': 'object', 'properties': {
            'query': {'type': 'string', 'description': '要找的内容，英文或中文都行'},
            'n': {'type': 'integer', 'minimum': 1, 'maximum': 30, 'description': '取几段，默认 8'},
            'where': {'type': 'string', 'enum': ['all', 'main', 'si'],
                      'description': 'all=正文+SI（默认）/ main=只正文 / si=只补充材料（配比、条件在这）'}},
         'required': ['query']},
        lambda a: library.render_retrieve(
            library.retrieve(a['query'], n=a.get('n', 8), where=a.get('where', 'all')), a['query']))

    server.register_tool(
        'library_refs',
        '这篇的参考文献列表，标出哪些已经在证据库里（可直接读）。模型读到 "[12]" 时用它'
        '知道 12 是谁；也是在证据库内部顺引用走的入口。纯脚本，零成本。',
        {'type': 'object', 'properties': dict(_KEY), 'required': ['itemKey']},
        lambda a: library.render_refs(library.refs(_k(a)), _k(a)))

    server.register_tool(
        'library_db_stats', '证据库有多大：篇数，以及有正文/SI/已解析各几篇。',
        {'type': 'object', 'properties': {}},
        lambda a: _db_stats())

    # ── 菜单与分组（2026-09-08 加）──────────────────────────────────
    # 为什么要这两个：整篇全文一口气几万字符，模型读三篇就把
    # 上下文吃掉一半。先给菜单（几百 token）、再按地址取需要的那两三节，
    # 成本大约是整篇的三十分之一。两个都只读免费，所以可以是 tool。
    server.register_tool(
        'library_outline',
        '这篇文献的骨架菜单：每节的地址(id)、类别(摘要/背景/合成/方法/结果/讨论/结论)、'
        '字数、含多少数字与表图；长节列到段（s5.p3），表（t1）和图注（f2）单独有地址。'
        '**读全文之前先看它**，然后用 library_section 只取要看的那几节/段/表。',
        {'type': 'object', 'properties': dict(_KEY), 'required': ['itemKey']},
        lambda a: _outline(library.outline(_k(a))))

    server.register_tool(
        'library_section',
        '按地址取这篇文献的原文：s5 一节 / s5.p3 一段 / t1 一张表（HTML 原样）/ f2 一条图注'
        '（地址来自 library_outline）。要补充材料 SI 里的就传 si=true。',
        {'type': 'object', 'properties': dict(_KEY, **{
            'sectionId': {'type': 'string', 'description': '地址，如 s4 / s4.p2 / t1 / f2（来自 library_outline）'},
            'si': {'type': 'boolean', 'description': '取补充材料 SI 里的节，默认 false'},
            'maxChars': {'type': 'integer', 'minimum': 100, 'maximum': 100000,
                         'description': f'返回字符上限，默认 {library.MAX_CHARS}'}}),
         'required': ['itemKey', 'sectionId']},
        lambda a: _section(library.section(
            _k(a), a['sectionId'], si=bool(a.get('si')),
            max_chars=a.get('maxChars', library.MAX_CHARS))))


# ── 返回值 → MCP 的 {text, structured}（纯转换）────────────────────────

def _outline(d):
    return {'text': library.render_outline(d), 'structured': d}


def _section(r):
    if not r['chars']:
        return {'text': '%s 的 %s 取不到：%s' % (r['itemKey'], r['id'], r['why_empty']),
                'structured': r}
    return {'text': r['text'] + ('\n…（已截断）' if r.get('truncated') else ''),
            'structured': {k: v for k, v in r.items() if k != 'text'}}


def _db_stats():
    s = library.db_stats()
    return (f"证据库 {s['papers']} 篇（带 DOI {s['with_doi']}）· 有正文 {s['pdf']} · 有 SI {s['si']} · "
            f"已解析 {s['fulltext']}（SI {s['si_fulltext']}）")
