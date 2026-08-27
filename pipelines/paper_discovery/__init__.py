# -*- coding: utf-8 -*-
"""paper_discovery · 文献发现基础件（公理：检索词/DOI → 相关文献列表）

职责：按方向补库——去 OpenAlex 搜相关文献，去重标记"库里已有"，返回结构化列表
（供人筛选或程序导入）。升级自早先的 find_papers.py（散脚本→干净公理件）。

用途聚焦：方向补库（广撒网+去重+可导入 Zotero 的字段）。

对外接口：
  - search(query, limit=25) → list[dict]（title/doi/year/authors/venue/abstract/
                                          cited/is_oa/in_library）
  - 未来可加 related(doi)（Semantic Scholar 引用网络）——按需扩展。

依赖：adapters.openalex（检索）+ adapters.zotero_client（查库里已有）。
"""
import os, sys, re, json

from adapters import openalex

try:
    from adapters.zotero_client import zget, USER_ID
except Exception:
    # 本机配置（Zotero 用户ID / 附件目录）统一从 core.config 读，换电脑只改 .env
    import os as _os, sys as _sys
    try:
        from core.config import need_site as _site
    except Exception:
        _site = lambda n: _os.environ.get(n) or (_ for _ in ()).throw(RuntimeError(f'缺少本机设置 {n}，请在控制面板或 .env 中配置'))
    _UID = _site('ZOTERO_USER_ID')
    _STORAGE = _site('ZOTERO_STORAGE')
    zget = None; USER_ID = os.environ.get('ZOTERO_USER_ID', _UID)

def _library_index():
    """取库里已有文献的标题/DOI 集合，用于去重标记。Zotero 没开则返回空。"""
    titles, dois = set(), set()
    if zget is None:
        return titles, dois
    try:
        start = 0
        while True:
            d = zget(f'/users/{USER_ID}/items/top?limit=100&start={start}')
            if not d:
                break
            for x in d:
                t = re.sub(r'[^a-z0-9]', '', (x['data'].get('title') or '').lower())
                if t:
                    titles.add(t)
                if x['data'].get('DOI'):
                    dois.add(x['data']['DOI'].lower())
            start += 100
            if len(d) < 100:
                break
    except Exception:
        pass
    return titles, dois




def search(query, limit=25, mailto='research@example.com'):
    """按检索词搜 OpenAlex，返回文献列表，并标出哪些库里已经有了。

    这就是本块的全部职责 —— **检索本身交给 adapters.openalex**，
    这里只做「外部结果 × 我的库」这一步编排。
    """
    have_titles, have_dois = _library_index()
    items, _total = openalex.search(query, limit=limit, mailto=mailto)
    for it in items:
        tnorm = re.sub(r'[^a-z0-9]', '', (it.get('title') or '').lower())
        it['in_library'] = (tnorm in have_titles) or ((it.get('doi') or '').lower() in have_dois)
    return items
