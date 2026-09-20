# -*- coding: utf-8 -*-
"""journalwatch 的 MCP 面：一个只读 tool（免费、可重来）。本文件只做参数转换。"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass


def _recent(a):
    from tools import journalwatch
    days = int(a.get('days') or 7)
    pick = (a.get('journal') or '').strip().lower()
    # 读雷达库，不现场问 Crossref：59 本刊串行两分多钟，MCP 客户端 60 秒就超时（踩坑 #172）
    try:
        r = journalwatch.recent_from_store(days=days, pick=pick, only_new=bool(a.get('only_new')))
    except Exception as e:
        return {'text': f'没查成：{type(e).__name__}: {e}', 'structured': {'ok': False}}
    rows = r['items']
    head = '%d 本刊、最近 %d 天：%d 篇（库里已有 %d 篇）' % (
        r['n_journals'], days, len(rows), sum(1 for w in rows if w['in_library']))
    if r['last_patrol']:
        head += ' · 雷达库最近一次巡逻：%s' % r['last_patrol']
    else:
        head += ' · ⚠ 这台机器还没巡逻过（雷达库是空的），主力机每天自动跑'
    lines = [head]
    for i, w in enumerate(rows[:200], 1):
        lines.append('%3d. [%s] %s · %s · %s · %s' % (
            i, '库' if w['in_library'] else '新', w['venue'], w['published'] or w['created'],
            (w['title'] or '')[:110], w['doi']))
    return {'text': '\n'.join(lines),
            'structured': {'ok': True, 'items': rows[:200], 'last_patrol': r['last_patrol']}}


def register(server):
    server.register_tool(
        'journalwatch_recent',
        '列出用户盯着的好期刊最近新登记的论文（读主力机每天巡逻好的雷达库，零网络、瞬时、只读），'
        '每篇标出证据库里有没有。想按关键词找文献 → 用 lit_search / discover；'
        '想收某几篇 → 让用户点 collect。',
        {'type': 'object', 'properties': {
            'days': {'type': 'integer', 'minimum': 1, 'maximum': 60, 'description': '看最近几天，默认 7'},
            'journal': {'type': 'string', 'description': '只看名字里带这个词的刊（可选）'},
            'only_new': {'type': 'boolean', 'description': '只列以前没见过的'}}},
        _recent,
        confirm=True)
