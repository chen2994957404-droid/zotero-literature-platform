# -*- coding: utf-8 -*-
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
"""litsearch 的 MCP 面：4 个只读工具（模型可以自己调，不花钱、不写东西、不弹窗）。

**本文件只做参数转换**：把 MCP 传来的 arguments 拆成 Python 参数、把返回值渲染成文本。
一行业务逻辑都不许写在这里 —— 逻辑在 `tools/litsearch/__init__.py`，
这样命令行与 MCP 两个入口共用同一份行为。

**为什么不加 confirm**：本包整包免费只读（`tool.toml` 里 `costs_money = false`、
`side_effects = []`），不属于「花钱或有副作用」那一档。对抗式检索一轮要调十几次，
每次弹窗等于废掉这个用法。
"""
from tools import litsearch

_DOI = {'doi': {'type': 'string', 'description': '文献的 DOI，如 10.1021/ma500632f'}}
_LIMIT = {'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100,
                    'description': '返回条数上限，默认见各工具'}}


def _line(it):
    """一条结果渲染成一行（带「库里有没有」）。"""
    mark = '【库里有】' if it.get('in_library') else '         '
    return '%s [%s] 被引%-5s %s\n           %s | %s' % (
        mark, it.get('year') or '????', it.get('citations') or 0,
        (it.get('title') or '')[:78],
        (it.get('venue') or '?')[:40], it.get('doi') or '(无 DOI)')


def _rows(items, head=''):
    if not items:
        return (head + '\n' if head else '') + '（没有结果）'
    return (head + '\n' if head else '') + '\n'.join(_line(it) for it in items)


def _search(a):
    items, total = litsearch.search(
        a.get('term') or '', limit=a.get('limit') or 25,
        year_from=a.get('yearFrom'), year_to=a.get('yearTo'))
    head = '全世界命中 %d 篇，返回前 %d 篇。' % (total, len(items))
    if total > len(items):
        head += '（命中远多于返回时，说明检索词还可以再收窄）'
    return _rows(items, head)


def _abstract(a):
    it = litsearch.abstract(a.get('doi') or '')
    if not it:
        return '查不到这个 DOI（OpenAlex 里没有收录，或 DOI 写错了）。'
    return '%s\n\n%s\n\n摘要：\n%s' % (
        it.get('title') or '(无标题)', _line(it),
        (it.get('abstract') or '(这篇没有摘要)'))


def register(server):
    """把本工具的 MCP 面挂到 server 上（聚合入口 host/mcp/server.py 会调这个）。"""

    server.register_tool(
        'lit_search',
        '**精确检索**全世界的文献：检索词必须真的出现在标题或摘要里（不是模糊相关性排序）。'
        '返回里带「这篇我库里有没有」，并告诉你全世界一共有多少篇 —— 命中数远大于返回数时，'
        '说明这个词还太宽，该收窄。免费、只读。'
        '词组要加引号，多词用 AND，例：`"phenylboronic acid" AND siloxane`。',
        {'type': 'object', 'properties': dict(
            {'term': {'type': 'string', 'description': '检索词（支持引号词组与 AND）'},
             'yearFrom': {'type': 'integer', 'description': '起始年份（含）'},
             'yearTo': {'type': 'integer', 'description': '结束年份（含）'}}, **_LIMIT),
         'required': ['term']},
        _search)

    server.register_tool(
        'lit_abstract',
        '按 DOI 取一篇的**完整摘要**。判断一篇贴不贴题、有没有你要的配方，靠读摘要，'
        '不要看标题猜。免费、只读。',
        {'type': 'object', 'properties': dict(_DOI), 'required': ['doi']},
        _abstract)

    server.register_tool(
        'lit_cited_by',
        '谁引用了这篇（**前向雪球**）—— 用来看「这个方向后来怎么发展的」。免费、只读。',
        {'type': 'object', 'properties': dict(_DOI, **_LIMIT), 'required': ['doi']},
        lambda a: _rows(litsearch.cited_by(a.get('doi') or '', a.get('limit') or 50)))

    server.register_tool(
        'lit_references',
        '这篇引用了谁（**后向雪球**）—— 用来看「这个方向的根在哪」。免费、只读。',
        {'type': 'object', 'properties': dict(_DOI, **_LIMIT), 'required': ['doi']},
        lambda a: _rows(litsearch.references(a.get('doi') or '', a.get('limit') or 50)))
