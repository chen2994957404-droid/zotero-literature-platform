# -*- coding: utf-8 -*-
"""zotero_client · Zotero 接口基础件（可独立成 GitHub 项目的候选）

职责：封装与 Zotero 的所有交互——读文献/附件/正文、定位本地正文 PDF。
这是「基础件拼装」愿景里的一块：下游（精读/抽取/向量化）都 import 它，
不再各自拷贝 find_pdf 等逻辑（消除技术债：曾有 3 份 find_pdf 拷贝）。

对外接口（稳定，供上层组合调用）：
  - zget(path)            : 本地只读 API GET
  - find_pdf(key)         : 定位正文 PDF 本地路径（优先信 Zotero 规范命名，排除 SI）
  - get_fulltext(att_key) : 取 Zotero 全文索引（粗层抽取/向量化用）

配置从环境变量读，带默认值（便于独立使用）。
"""
import os, re, json, urllib.request

# 本机配置（Zotero 用户ID / 附件目录）统一从 modules.config 读，换电脑只改 .env
import os as _os, sys as _sys
try:
    from modules.config import need_site as _site, get_site as _gsite
except Exception:
    _site = lambda n: _os.environ.get(n) or (_ for _ in ()).throw(RuntimeError(f'缺少本机设置 {n}，请在控制面板或 .env 中配置'))
    _gsite = lambda n: _os.environ.get(n, '')
_UID = _site('ZOTERO_USER_ID')
_STORAGE = _site('ZOTERO_STORAGE')
USER_ID = os.environ.get('ZOTERO_USER_ID', _UID)
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


def get_fulltext(att_key):
    """取 Zotero 自带全文索引文本（不解析 PDF）。用于粗层抽取/向量化。"""
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            LOCAL_API + f'/users/{USER_ID}/items/{att_key}/fulltext', headers=_H), timeout=20).read()
        return json.loads(r).get('content', '')
    except Exception:
        return ''
