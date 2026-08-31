# -*- coding: utf-8 -*-
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
"""library 的 MCP 面：9 个只读工具（模型可以自己调，不花钱、不写东西）。

**本文件只做参数转换**：把 MCP 传来的 arguments 拆成 Python 参数、把返回值
渲染成文本。一行业务逻辑都不许写在这里 —— 逻辑在 `tools/library/__init__.py`，
那样命令行、面板、MCP 三个入口共用同一份行为，不会各说各话。

R4 窗（2026-08-31）从 `host/mcp/zotero_server.py` 拆过来的 9 个。
第 10 个 `ping` 是服务自己的存活检查，不属于任何工具，留在 `host/mcp/server.py`。
"""
from tools import library

_KEY = {'itemKey': {'type': 'string', 'description': 'Zotero 条目 key（8 位字母数字）'}}


def register(server):
    """把本工具的 MCP 面挂到 server 上（聚合入口 host/mcp/server.py 会调这个）。"""

    server.register_tool(
        'library_stats', '我的库有多大：条目/合集/标签数量，以及 Zotero 通不通。',
        {'type': 'object', 'properties': {}},
        lambda a: _stats())

    server.register_tool(
        'library_search', '按关键词/标签/类型/合集搜我库里的文献（顶层条目）。',
        {'type': 'object', 'properties': {
            'query': {'type': 'string', 'description': '搜索词'},
            'qmode': {'type': 'string', 'enum': ['titleCreatorYear', 'everything'],
                      'description': '默认 titleCreatorYear（准）；everything 连全文一起搜（广）'},
            'tag': {'type': 'string', 'description': '按标签精确过滤'},
            'itemType': {'type': 'string', 'description': '按条目类型过滤'},
            'collection': {'type': 'string', 'description': '合集 key，只搜该合集'},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100,
                      'description': '返回条数，默认 25'},
            'start': {'type': 'integer', 'minimum': 0, 'description': '跳过前 N 条'},
        }},
        lambda a: _items(library.search(
            query=a.get('query'), qmode=a.get('qmode', 'titleCreatorYear'),
            tag=a.get('tag'), item_type=a.get('itemType'),
            collection=a.get('collection'), limit=a.get('limit', 25),
            start=a.get('start', 0))))

    server.register_tool(
        'library_item', '按 key 取单篇完整信息：元数据、附件、笔记数、正文 PDF 路径。',
        {'type': 'object', 'properties': dict(_KEY), 'required': ['itemKey']},
        lambda a: _item(library.item(a['itemKey'])))

    server.register_tool(
        'library_pdf', '定位某篇文献的正文 PDF 本地路径（自动排除补充材料 SI）。',
        {'type': 'object', 'properties': dict(_KEY), 'required': ['itemKey']},
        lambda a: _pdf(library.pdf(a['itemKey'])))

    server.register_tool(
        'library_fulltext',
        '取某篇文献的正文全文（Zotero 全文索引，免费瞬时；无索引会说明原因）。',
        {'type': 'object', 'properties': dict(_KEY, **{
            'maxChars': {'type': 'integer', 'minimum': 100, 'maximum': 100000,
                         'description': f'返回字符上限，默认 {library.MAX_CHARS}'}}),
         'required': ['itemKey']},
        lambda a: _fulltext(library.fulltext(
            a['itemKey'], max_chars=a.get('maxChars', library.MAX_CHARS))))

    server.register_tool(
        'library_collections', '列出全部合集（含父子层级）。',
        {'type': 'object', 'properties': {}},
        lambda a: _collections(library.collections()))

    server.register_tool(
        'library_collection_items', '列出某个合集里的文献。',
        {'type': 'object', 'properties': {
            'collectionKey': {'type': 'string'},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100},
        }, 'required': ['collectionKey']},
        lambda a: _items(library.collection_items(
            a['collectionKey'], limit=a.get('limit', 25))))

    server.register_tool(
        'library_tags', '列出全部标签及各自文献数（降序）。',
        {'type': 'object', 'properties': {}},
        lambda a: _tags(library.tags()))

    server.register_tool(
        'library_recent', '最近 N 天内新增/修改的文献。',
        {'type': 'object', 'properties': {
            'days': {'type': 'integer', 'minimum': 1, 'maximum': 3650,
                     'description': '回溯天数，默认 7'},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100},
        }},
        lambda a: _items(library.recent(days=a.get('days', 7),
                                        limit=a.get('limit', 25))))


# ── 返回值 → MCP 的 {text, structured}（纯转换）────────────────────────

def _stats():
    s = library.stats()
    if not s['zotero_reachable']:
        return {'text': 'Zotero 本地 API 不可达：请确认 Zotero 桌面已打开，且设置了'
                        '「允许其他应用与本机上的 Zotero 通信」。', 'structured': s}
    return {'text': f"顶层条目 {s['top_items']} · 合集 {s['collections']} "
                    f"· 标签 {s['tags']}", 'structured': s}


def _items(items):
    return {'text': library.render_items(items),
            'structured': {'count': len(items), 'items': items}}


def _item(detail):
    return {'text': library.render_item(detail), 'structured': detail}


def _pdf(r):
    return {'text': r['pdf_path'] or f"{r['itemKey']} 未找到正文 PDF"
                                     f"（可能无 PDF 附件或只有补充材料）。",
            'structured': r}


def _fulltext(r):
    if not r['chars']:
        return {'text': f"{r['itemKey']} 取不到全文：{r['why_empty']}", 'structured': r}
    return {'text': r['text'] + ('\n…（已截断，全文更长）' if r['truncated'] else ''),
            'structured': {k: v for k, v in r.items() if k != 'text'}}


def _collections(cols):
    return {'text': library.render_collections(cols),
            'structured': {'count': len(cols), 'collections': cols}}


def _tags(rows):
    return {'text': library.render_tags(rows),
            'structured': {'count': len(rows), 'tags': rows}}
