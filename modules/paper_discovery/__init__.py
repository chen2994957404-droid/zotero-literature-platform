# -*- coding: utf-8 -*-
"""paper_discovery · 文献发现基础件（公理：检索词/DOI → 相关文献列表）

职责：按方向补库——去 OpenAlex 搜相关文献，去重标记"库里已有"，返回结构化列表
（供人筛选或程序导入）。升级自早先的 find_papers.py（散脚本→干净公理件）。

用途聚焦：方向补库（广撒网+去重+可导入 Zotero 的字段）。

对外接口：
  - search(query, limit=25) → list[dict]（title/doi/year/authors/venue/abstract/
                                          cited/is_oa/in_library）
  - 未来可加 related(doi)（Semantic Scholar 引用网络）——按需扩展。

依赖：Python 标准库 + zotero_client（查库里已有）。OpenAlex 免费无需 key。
"""
import os, sys, re, json, urllib.request, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
try:
    from modules.zotero_client import zget, USER_ID
except Exception:
    # 本机配置（Zotero 用户ID / 附件目录）统一从 modules.config 读，换电脑只改 .env
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    try:
        from modules.config import need_site as _site
    except Exception:
        _site = lambda n: _os.environ.get(n) or (_ for _ in ()).throw(RuntimeError(f'缺少本机设置 {n}，请在控制面板或 .env 中配置'))
    _UID = _site('ZOTERO_USER_ID')
    _STORAGE = _site('ZOTERO_STORAGE')
    zget = None; USER_ID = os.environ.get('ZOTERO_USER_ID', _UID)

OPENALEX = 'https://api.openalex.org/works'


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


def _restore_abstract(inv):
    """OpenAlex 用倒排索引存摘要，还原成正常文本。"""
    if not inv:
        return ''
    words = {}
    for word, positions in inv.items():
        for p in positions:
            words[p] = word
    return ' '.join(words[k] for k in sorted(words))


def search(query, limit=25, mailto='research@example.com'):
    """按检索词搜 OpenAlex，返回结构化文献列表，标记库里已有。"""
    have_titles, have_dois = _library_index()
    url = (f'{OPENALEX}?search={urllib.parse.quote(query)}'
           f'&per-page={min(limit, 200)}&sort=relevance_score:desc&mailto={mailto}')
    req = urllib.request.Request(url, headers={'User-Agent': 'research'})
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())
    out = []
    for w in r.get('results', []):
        doi = (w.get('doi') or '').replace('https://doi.org/', '')
        pl = w.get('primary_location') or {}
        venue = (pl.get('source') or {}).get('display_name', '') if pl.get('source') else ''
        auth = w.get('authorships', [])
        first_author = auth[0]['author']['display_name'] if auth else ''
        tnorm = re.sub(r'[^a-z0-9]', '', (w.get('title') or '').lower())
        in_lib = (tnorm in have_titles) or (doi.lower() in have_dois)
        out.append({
            'title': w.get('title', ''),
            'doi': doi,
            'year': w.get('publication_year'),
            'first_author': first_author,
            'venue': venue,
            'abstract': _restore_abstract(w.get('abstract_inverted_index'))[:400],
            'cited_by': w.get('cited_by_count', 0),
            'is_oa': bool((w.get('open_access') or {}).get('is_oa')),
            'in_library': in_lib,
        })
    return out
