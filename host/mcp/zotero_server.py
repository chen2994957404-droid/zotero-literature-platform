# -*- coding: utf-8 -*-
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
"""zotero_server · 库房层 MCP 服务（只读工具集，供 agent 调用）

谁调用它：MCP 客户端（Claude Code / Cursor / DSH 等）以 stdio 子进程方式启动本文件；
本文件把平台现有的 shared/adapters/zotero_client（公理件）包成 10 个只读 MCP 工具。

设计决策（详见 host/mcp/CLAUDE.md）：
  - v1 只读：搜/查/找 PDF/取全文/合集/标签/统计——零写操作，最安全，agent 可直接调；
  - 写操作（打标签/改名/去重/清理）留 v2，届时走 dry-run + 显式确认参数，并与
    watcher 的标签状态机协调（本 v1 不动 Zotero 任何数据）；
  - 工具面参考 nealcaren/mcp-zotero（零号判据调研结论：库房层「借鉴重写」优于搬运）；
  - 本地 API 细节（q/qmode/tag/collection/sort 参数、Total-Results 头）按 Zotero
    Web API 同构实现，真实库连通验证见 变更记录。

对外接口（MCP 工具，均为只读）：
  ping / library_stats / search_items / get_item / find_pdf / get_fulltext /
  list_collections / get_collection_items / list_tags / get_recent_items
"""
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from shared.kernel.config import need_site
from shared.adapters.zotero_client import LOCAL_API, find_pdf, get_fulltext, zget
from shared.kernel.cli import flag

VERSION = '0.1.0'
_HDR = {'Zotero-Allowed-Request': 'true'}   # 本地 API 要求的请求头（与 zotero_client 一致）

_uid_cache = None


def _uid():
    """取 Zotero 用户 ID（走 config，没配会给出怎么配的明确报错）。"""
    global _uid_cache
    if _uid_cache is None:
        _uid_cache = need_site('ZOTERO_USER_ID')
    return _uid_cache


def _api_count(path):
    """只读计数：读 Zotero API 的 Total-Results 头。不可达返回 None（由调用方决定文案）。"""
    try:
        req = urllib.request.Request(LOCAL_API + path, headers=_HDR)
        with urllib.request.urlopen(req, timeout=5) as r:
            return int(r.headers.get('Total-Results') or 0)
    except Exception:
        return None


def _simplify(item):
    """把 Zotero 条目压成扁平 dict（借鉴 nealcaren/mcp-zotero 的 _simplify_item）。"""
    d = item.get('data') if isinstance(item, dict) else {}
    names = []
    for c in d.get('creators') or []:
        if c.get('name'):
            names.append(c['name'])
        else:
            names.append(' '.join(x for x in (c.get('lastName'), c.get('firstName')) if x))
    return {
        'key': item.get('key') or d.get('key'),
        'itemType': d.get('itemType'),
        'title': d.get('title'),
        'creators': names,
        'date': d.get('date'),
        'publicationTitle': d.get('publicationTitle'),
        'DOI': d.get('DOI'),
        'url': d.get('url'),
        'tags': [t.get('tag') for t in d.get('tags') or []],
    }


def _items_to_text(items, total=None):
    """条目列表 → 模型可读的 markdown。"""
    if not items:
        return '（无结果）'
    lines = []
    if total is not None:
        lines.append(f'共 {total} 条，显示前 {len(items)} 条：')
        lines.append('')
    for it in items:
        head = f"### {it.get('title') or '(无标题)'}"
        if it.get('date'):
            head += f"（{it['date']}）"
        lines.append(head)
        meta = []
        if it.get('creators'):
            meta.append('; '.join(it['creators'][:6]))
        if it.get('publicationTitle'):
            meta.append(it['publicationTitle'])
        if it.get('itemType'):
            meta.append(it['itemType'])
        if meta:
            lines.append('> ' + ' · '.join(meta))
        if it.get('tags'):
            lines.append('标签：' + ', '.join(it['tags']))
        if it.get('DOI'):
            lines.append('DOI：' + it['DOI'])
        lines.append(f"key：{it.get('key')}")
        lines.append('')
    return '\n'.join(lines).rstrip()


def _search_path(args):
    """拼 Zotero 搜索路径（q/qmode/tag/itemType/collection/limit/start，与 Web API 同构）。"""
    uid = _uid()
    limit = int(args.get('limit', 25))
    start = int(args.get('start', 0))
    parts = [f'/users/{uid}/items/top?format=json',
             f'limit={limit}', f'start={start}',
             f"qmode={args.get('qmode', 'titleCreatorYear')}"]
    if args.get('query'):
        parts.append('q=' + urllib.parse.quote(str(args['query'])))
    if args.get('tag'):
        parts.append('tag=' + urllib.parse.quote(str(args['tag'])))
    if args.get('itemType'):
        parts.append('itemType=' + urllib.parse.quote(str(args['itemType'])))
    if args.get('collection'):
        parts.append('collection=' + urllib.parse.quote(str(args['collection'])))
    return '&'.join(parts)


def _single_item(key):
    """按 key 取单条目（本地 API 单条返回对象，兼容列表形态）。"""
    data = zget(f'/users/{_uid()}/items/{key}')
    return data[0] if isinstance(data, list) and data else data


# ── 工具 1/10：ping ────────────────────────────────────────────────────

def _ping(args):
    return {'text': json.dumps({'ok': True, 'server': 'zotero-mcp', 'version': VERSION},
                               ensure_ascii=False),
            'structured': {'ok': True, 'server': 'zotero-mcp', 'version': VERSION}}


# ── 工具 2/10：library_stats ───────────────────────────────────────────

def _library_stats(args):
    uid = _uid()
    counts = {
        'top_items': _api_count(f'/users/{uid}/items/top?limit=1'),
        'collections': _api_count(f'/users/{uid}/collections?limit=1'),
        'tags': _api_count(f'/users/{uid}/tags?limit=1'),
    }
    reachable = any(v is not None for v in counts.values())
    if not reachable:
        return {'text': 'Zotero 本地 API 不可达：请确认 Zotero 桌面已打开，且设置了'
                        '「允许其他应用与本机上的 Zotero 通信」。',
                'structured': {'zotero_reachable': False}, 'is_error': False}
    return {'text': json.dumps(counts, ensure_ascii=False),
            'structured': {'zotero_reachable': True, **counts}}


# ── 工具 3/10：search_items ────────────────────────────────────────────

def _search_items(args):
    items = [_simplify(i) for i in zget(_search_path(args))]
    return {'text': _items_to_text(items), 'structured': {'count': len(items), 'items': items}}


# ── 工具 4/10：get_item ────────────────────────────────────────────────

def _get_item(args):
    key = args['itemKey']
    item = _single_item(key)
    simp = _simplify(item)
    atts, notes = [], 0
    try:
        for c in zget(f'/users/{_uid()}/items/{key}/children'):
            t = c.get('data', {}).get('itemType')
            if t == 'attachment':
                atts.append({'key': c['key'], 'title': c.get('data', {}).get('title'),
                             'contentType': c.get('data', {}).get('contentType')})
            elif t == 'note':
                notes += 1
    except Exception:
        pass  # 子条目取不到不阻塞主结果（Zotero 偶尔同步中）
    pdf_path, pdf_att = find_pdf(key, return_att_key=True)
    structured = {
        'item': simp,
        'attachments': atts,
        'notes_count': notes,
        'pdf_path': pdf_path,
        'pdf_attachment_key': pdf_att,
    }
    lines = [f"# {simp.get('title') or '(无标题)'}"]
    if simp.get('date'):
        lines.append(f"日期：{simp['date']}")
    if simp.get('creators'):
        lines.append('作者：' + '; '.join(simp['creators']))
    if simp.get('publicationTitle'):
        lines.append('期刊/来源：' + simp['publicationTitle'])
    if simp.get('DOI'):
        lines.append('DOI：' + simp['DOI'])
    if simp.get('url'):
        lines.append('URL：' + simp['url'])
    if simp.get('tags'):
        lines.append('标签：' + ', '.join(simp['tags']))
    lines.append(f"key：{simp.get('key')}")
    if atts:
        lines.append('')
        lines.append('附件：')
        for a in atts:
            lines.append(f"  - {a.get('title') or '(无标题)'} [{a.get('contentType')}] {a['key']}")
    lines.append(f"笔记数：{notes}")
    if pdf_path:
        lines.append('')
        lines.append(f"正文 PDF：{pdf_path}（附件 {pdf_att}）")
    else:
        lines.append('')
        lines.append('正文 PDF：未找到（可能没有 PDF 附件，或只有补充材料）')
    return {'text': '\n'.join(lines), 'structured': structured}


# ── 工具 5/10：find_pdf ────────────────────────────────────────────────

def _find_pdf(args):
    key = args['itemKey']
    pdf_path, pdf_att = find_pdf(key, return_att_key=True)
    if not pdf_path:
        return {'text': f'{key} 未找到正文 PDF（可能无 PDF 附件或只有补充材料）。',
                'structured': {'itemKey': key, 'pdf_path': None}, 'is_error': False}
    return {'text': f'正文 PDF：{pdf_path}',
            'structured': {'itemKey': key, 'pdf_path': pdf_path,
                           'attachment_key': pdf_att}}


# ── 工具 6/10：get_fulltext ────────────────────────────────────────────

def _get_fulltext(args):
    key = args['itemKey']
    max_chars = int(args.get('maxChars', 20000))
    _, pdf_att = find_pdf(key, return_att_key=True)
    if not pdf_att:
        return {'text': f'{key} 无正文 PDF 附件，取不到全文。',
                'structured': {'itemKey': key, 'chars': 0}, 'is_error': False}
    text = get_fulltext(pdf_att)
    if not text:
        return {'text': f'{key} 的 Zotero 全文索引为空（可能未建索引，或扫描件无文本层）。',
                'structured': {'itemKey': key, 'chars': 0}, 'is_error': False}
    truncated = len(text) > max_chars
    text = text[:max_chars]
    return {'text': text + ('\n…（已截断，全文更长）' if truncated else ''),
            'structured': {'itemKey': key, 'chars': len(text), 'truncated': truncated}}


# ── 工具 7/10：list_collections ────────────────────────────────────────

def _list_collections(args):
    cols = zget(f'/users/{_uid()}/collections?limit=100&format=json')
    by_parent = {}
    for c in cols:
        d = c.get('data', {})
        by_parent.setdefault(d.get('parentCollection'), []).append(
            {'key': c['key'], 'name': d.get('name')})

    def render(parent):
        out = []
        for c in sorted(by_parent.get(parent, []), key=lambda x: x['name']):
            out.append(f"- {c['name']} ({c['key']})")
            out.extend('  ' + l for l in render(c['key']))
        return out

    lines = [f'共 {len(cols)} 个合集：', ''] + render(None)
    return {'text': '\n'.join(lines),
            'structured': {'count': len(cols),
                           'collections': [{'key': c['key'], 'name': c.get('data', {}).get('name')}
                                           for c in cols]}}


# ── 工具 8/10：get_collection_items ────────────────────────────────────

def _get_collection_items(args):
    key = args['collectionKey']
    limit = int(args.get('limit', 25))
    items = [_simplify(i) for i in zget(
        f'/users/{_uid()}/collections/{key}/items/top?limit={limit}&format=json')]
    return {'text': _items_to_text(items),
            'structured': {'collectionKey': key, 'count': len(items), 'items': items}}


# ── 工具 9/10：list_tags ───────────────────────────────────────────────

def _list_tags(args):
    tags = zget(f'/users/{_uid()}/tags?limit=100&format=json')
    rows = []
    for t in tags:
        n = t.get('meta', {}).get('numItems') or 0
        rows.append({'tag': t.get('tag'), 'numItems': n})
    rows.sort(key=lambda r: r['numItems'], reverse=True)
    text = '标签（按文献数降序）：\n' + '\n'.join(
        f"- {r['tag']}（{r['numItems']} 篇）" for r in rows)
    return {'text': text, 'structured': {'count': len(rows), 'tags': rows}}


# ── 工具 10/10：get_recent_items ───────────────────────────────────────

def _get_recent_items(args):
    days = int(args.get('days', 7))
    limit = int(args.get('limit', 25))
    items = zget(f'/users/{_uid()}/items/top?sort=dateModified&direction=desc'
                 f'&limit=100&format=json')

    def _within(iso):
        try:
            dt = datetime.fromisoformat((iso or '').replace('Z', '+00:00'))
        except Exception:
            return True  # 解析不了日期的保守保留
        return (datetime.now(timezone.utc) - dt).total_seconds() <= days * 86400

    recent = [i for i in items if _within(i.get('data', {}).get('dateModified'))][:limit]
    simp = [_simplify(i) for i in recent]
    return {'text': _items_to_text(simp),
            'structured': {'days': days, 'count': len(simp), 'items': simp}}


# ── 工具注册表 ─────────────────────────────────────────────────────────

def build_server():
    """装配带全部只读工具的 MCP 服务。"""
    from host.mcp.stdio import MCPStdioServer
    s = MCPStdioServer('zotero-mcp', VERSION)

    s.register_tool('ping', '存活检查：确认 MCP 服务本身在跑。',
                    {'type': 'object', 'properties': {}}, _ping)

    s.register_tool('library_stats', '库统计：Zotero 本地 API 是否可达，以及条目/合集/标签数量。',
                    {'type': 'object', 'properties': {}}, _library_stats)

    s.register_tool('search_items', '按关键词/标签/类型/合集搜索库内文献（顶层条目）。',
                    {'type': 'object',
                     'properties': {
                         'query': {'type': 'string', 'description': '搜索词（标题/作者/年份）'},
                         'qmode': {'type': 'string', 'enum': ['titleCreatorYear', 'everything'],
                                   'description': '搜索范围，默认 titleCreatorYear'},
                         'tag': {'type': 'string', 'description': '按标签精确过滤'},
                         'itemType': {'type': 'string', 'description': '按条目类型过滤'},
                         'collection': {'type': 'string', 'description': '合集 key，只搜该合集'},
                         'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100,
                                   'description': '返回条数，默认 25'},
                         'start': {'type': 'integer', 'minimum': 0, 'description': '跳过前 N 条'},
                     }}, _search_items)

    s.register_tool('get_item', '按 key 取单篇文献完整信息：元数据、附件、笔记数、正文 PDF 路径。',
                    {'type': 'object',
                     'properties': {'itemKey': {'type': 'string',
                                                'description': 'Zotero 条目 key（8 位字母数字）'}},
                     'required': ['itemKey']}, _get_item)

    s.register_tool('find_pdf', '定位某篇文献的正文 PDF 本地路径（自动排除补充材料 SI）。',
                    {'type': 'object',
                     'properties': {'itemKey': {'type': 'string'}},
                     'required': ['itemKey']}, _find_pdf)

    s.register_tool('get_fulltext', '取某篇文献正文全文文本（Zotero 全文索引；无索引返回空并说明）。',
                    {'type': 'object',
                     'properties': {
                         'itemKey': {'type': 'string'},
                         'maxChars': {'type': 'integer', 'minimum': 100, 'maximum': 100000,
                                      'description': '返回字符上限，默认 20000'},
                     },
                     'required': ['itemKey']}, _get_fulltext)

    s.register_tool('list_collections', '列出全部合集（含父子层级）。',
                    {'type': 'object', 'properties': {}}, _list_collections)

    s.register_tool('get_collection_items', '列出某个合集里的文献。',
                    {'type': 'object',
                     'properties': {
                         'collectionKey': {'type': 'string'},
                         'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100},
                     },
                     'required': ['collectionKey']}, _get_collection_items)

    s.register_tool('list_tags', '列出全部标签及各自文献数（降序）。',
                    {'type': 'object', 'properties': {}}, _list_tags)

    s.register_tool('get_recent_items', '最近 N 天内新增/修改的文献。',
                    {'type': 'object',
                     'properties': {
                         'days': {'type': 'integer', 'minimum': 1, 'maximum': 3650,
                                  'description': '回溯天数，默认 7'},
                         'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100},
                     }}, _get_recent_items)
    return s


def main():
    """入口：--list 打印工具清单（给人看），否则启动 MCP stdio 服务。"""
    if flag('--list'):
        for t in build_server()._tools:
            print(f"{t['name']}\t{t['description']}")
        return
    build_server().serve()


if __name__ == '__main__':
    main()
