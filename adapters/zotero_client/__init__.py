# -*- coding: utf-8 -*-
"""zotero_client · Zotero 接口基础件（可独立成 GitHub 项目的候选）

职责：封装与 Zotero 的所有交互——读文献/附件/正文、定位本地正文 PDF。
这是「基础件拼装」愿景里的一块：下游（精读/抽取/向量化）都 import 它，
不再各自拷贝 find_pdf 等逻辑（消除技术债：曾有 3 份 find_pdf 拷贝）。

对外接口（稳定，供上层组合调用）：
  - zget(path)            : 本地只读 API GET（滞后于云端，见 zweb）
  - zweb(path)            : 云端只读 API GET（自己刚写的东西要问它）
  - find_child_attachment : 找某文献下指定标题的附件（云端优先）
  - replace_tags / upload_attachment : **写**（在 _write.py，每个都带机器角色守卫）
  - USER_ID / WEB_USER_ID : 本地 API 的 id / 写 zotero.org 的真实数字 id（两者不同）
  - find_pdf(key)         : 定位正文 PDF 本地路径（优先信 Zotero 规范命名，排除 SI）
  - get_fulltext(att_key) : 取 Zotero 全文索引（粗层抽取/向量化用）

配置从环境变量读，带默认值（便于独立使用）。
"""
import os, re, json, urllib.request, urllib.parse

# 本机配置（Zotero 用户ID / 附件目录）统一从 core.config 读，换电脑只改 .env
import os as _os, sys as _sys
try:
    from core.config import need_site as _site, get_site as _gsite
except Exception:
    _site = lambda n: _os.environ.get(n) or (_ for _ in ()).throw(RuntimeError(f'缺少本机设置 {n}，请在控制面板或 .env 中配置'))
    _gsite = lambda n: _os.environ.get(n, '')
_UID = _site('ZOTERO_USER_ID')
_STORAGE = _site('ZOTERO_STORAGE')
USER_ID = os.environ.get('ZOTERO_USER_ID', _UID)      # 本地 API 用（可以是 0）
# 写 zotero.org 用的**真实数字 id** —— 与本地 API 的 id 不是一回事。
# 没单独配就沿用上面那个（行为与从前一致）。
try:
    from core.config import web_user_id as _web_uid
    WEB_USER_ID = os.environ.get('ZOTERO_WEB_USER_ID') or _web_uid() or USER_ID
except Exception:
    WEB_USER_ID = os.environ.get('ZOTERO_WEB_USER_ID', USER_ID)
STORAGE_DIR = os.environ.get('ZOTERO_STORAGE', _STORAGE)
# ⚠ 地址必须走 config（踩坑 #46）：原来只读 ZOTERO_LOCAL_API 这个键，
# 而控制面板存的是 ZOTERO_API_HOST —— 键名对不上，用户在面板里改地址永远不生效，
# 建在本积木之上的 MCP 服务也跟着一起失效。ZOTERO_LOCAL_API 保留作旧配置兼容。
LOCAL_API = (os.environ.get('ZOTERO_LOCAL_API')
             or (_gsite('ZOTERO_API_HOST') or 'http://localhost:23119') + '/api')
_H = {'Zotero-Allowed-Request': 'true'}

# 补充材料/附录 命名特征（含踩坑#15 的 Springer MOESM/ESM 补丁）
SUPP_PAT = re.compile(
    r'suppmat|supp\b|supporting|supplement|-si-|_si_|\bsi\.pdf|appendix|'
    r'moesm|_esm\b|electronic.?supplementary', re.I)


def zget(path):
    """本地只读 API GET。path 如 '/users/<id>/items/<key>/children'。"""
    req = urllib.request.Request(LOCAL_API + path, headers=_H)
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def _local_uid():
    """本地 API 也要用户 id。模块顶部已经用 need_site 取过（缺了 import 就会失败），
    这里只做兜底，用 USER_ID 而不是再抛一个自定义异常 ——
    曾经这里写了个根本没定义的 ZoteroError，一旦触发就是 NameError，
    而它偏偏只在「配置缺失、最需要看清报错」时触发。"""
    return USER_ID or _site('ZOTERO_USER_ID')


def search_items(query='', limit=100, qmode='everything', tag=None,
                 item_type=None, collection=None, start=0):
    """按关键词/标签/类型/合集搜库内顶层条目，返回 Zotero 原始条目列表。

    **只服务本机**：Zotero 的本地 API 只监听 localhost，所以这个函数只能在
    Zotero 正在跑的那台机器上用（见 docs/两台机器的分工.md）。
    编程端调它会连不上 —— 那不是 bug，调用方应当捕获后跳过。

    qmode 默认 'everything'（连全文一起搜），比 'titleCreatorYear' 召回高得多；
    要精确匹配标题作者年份时才传后者。
    """
    parts = ['/users/%s/items/top?format=json' % _local_uid(),
             'limit=%d' % int(limit), 'start=%d' % int(start),
             'qmode=%s' % qmode]
    for k, v in (('q', query), ('tag', tag), ('itemType', item_type),
                 ('collection', collection)):
        if v:
            parts.append('%s=%s' % (k, urllib.parse.quote(str(v))))
    return zget('&'.join(parts))


def dois_of(items):
    """一批 Zotero 条目 → 去重后的 DOI 列表（没有 DOI 的静默跳过）。"""
    out = []
    for it in items or ():
        data = it.get('data') if isinstance(it, dict) and 'data' in it else it
        d = ((data or {}).get('DOI') or '').strip().lower()
        d = d.replace('https://doi.org/', '').rstrip('.')
        if d and d not in out:
            out.append(d)
    return out


# ── zotero.org（云端）──────────────────────────────────────────────
# 与云端打交道的实现全在 _web.py —— 它是全项目唯一出现那个域名的文件，
# 写操作的机器角色守卫也都在那里。这里只做再导出。
from adapters.zotero_client._web import (WEB_API, zweb, get_item, patch_item,
                                         create_items, delete_item,
                                         replace_tags, upload_attachment,
                                         check_key)


def find_child_attachment(item_key, title):
    """找某条文献下标题为 title 的附件，返回它的 key；没有则 None。

    **先问云端，读不到再退回本地**：用途是「我上次传的那个还在不在」，
    而这个问题只有云端答得准。云端不可达（没配 key / 断网）时退回本地 ——
    退化的后果是可能重复建一个附件，比整篇精读白做轻。
    """
    for fetch in (lambda: zweb(f'/items/{item_key}/children'),
                  lambda: zget(f'/users/{USER_ID}/items/{item_key}/children')):
        try:
            children = fetch()
        except Exception:
            continue
        for c in children:
            d = c['data']
            if (d.get('itemType') == 'attachment'
                    and (d.get('title') or '').strip() == title):
                return c['key']
        return None          # 问到了，确实没有 —— 不必再问下一个来源
    return None


def find_pdf(item_key, return_att_key=False):
    """定位文献正文 PDF 的本地路径（踩坑 #15、find_pdf 工单的单一实现）。

    优先级：① title=='Full Text PDF' 的规范正文（最可靠）
            ② 非补充材料里选最大的（未规范化命名的兜底）
    return_att_key=True 时返回 (path, att_key)，否则只返回 path。找不到返回 None（或 (None,None)）。
    """
    try:
        children = zget(f'/users/{USER_ID}/items/{item_key}/children')
    except Exception:
        return (None, None) if return_att_key else None
    cands = []  # (path, att_key, size, is_supp, is_fulltext)
    for c in children:
        d = c['data']
        if d.get('itemType') == 'attachment' and d.get('contentType') == 'application/pdf':
            att_key = c['key']
            title = (d.get('title') or '').strip()
            is_supp_title = bool(SUPP_PAT.search(title)) or title.upper() == 'SI'
            is_fulltext = title.lower() == 'full text pdf'
            dd = os.path.join(STORAGE_DIR, att_key)
            if os.path.isdir(dd):
                for f in os.listdir(dd):
                    if f.lower().endswith('.pdf'):
                        fp = os.path.join(dd, f)
                        try: size = os.path.getsize(fp)
                        except: size = 0
                        is_supp = bool(SUPP_PAT.search(f)) or is_supp_title
                        cands.append((fp, att_key, size, is_supp, is_fulltext))
    if not cands:
        return (None, None) if return_att_key else None
    ft = [c for c in cands if c[4] and not c[3]]
    pool = ft if ft else ([c for c in cands if not c[3]] or cands)
    pool.sort(key=lambda c: c[2], reverse=True)
    best = pool[0]
    return (best[0], best[1]) if return_att_key else best[0]


# Elsevier 的 SI 常是 .docx 而不是 PDF
DOCX_CT = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


def has_si(item_key):
    """该文献有没有补充材料（SI）附件。支持 PDF 与 .docx。

    判断依据与 find_pdf 共用同一个 SUPP_PAT —— 重构前 zotero_watcher 里
    另有一份拷贝，而且那份把正则**写在了循环体内**（每个附件重新编译一次）。
    同一个判断散成三份的后果是：改了一处、另两处照旧，行为悄悄分叉。
    """
    try:
        children = zget(f'/users/{USER_ID}/items/{item_key}/children')
    except Exception:
        return False      # Zotero 没开时按「没有 SI」处理，不阻断主流程
    for c in children:
        d = c['data']
        if d.get('itemType') != 'attachment':
            continue
        if d.get('contentType') not in ('application/pdf', DOCX_CT):
            continue
        title = (d.get('title') or '').strip()
        fn = d.get('filename') or ''
        if SUPP_PAT.search(title) or SUPP_PAT.search(fn) or title.upper() == 'SI':
            return True
    return False


def get_fulltext(att_key):
    """取 Zotero 自带全文索引文本（不解析 PDF）。用于粗层抽取/向量化。"""
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            LOCAL_API + f'/users/{USER_ID}/items/{att_key}/fulltext', headers=_H), timeout=20).read()
        return json.loads(r).get('content', '')
    except Exception:
        return ''
