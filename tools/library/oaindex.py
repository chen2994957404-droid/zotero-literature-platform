# -*- coding: utf-8 -*-
"""tools.library.oaindex · 证据库每篇的「作者 + 摘要」索引（从 OpenAlex 取一次，存本地）。

**为什么要有**（2026-10-11）：证据库目录卡（meta.json）里没有作者 —— 主力机 1207 篇一篇都没存，
更没标谁是通讯。按通讯作者检索、把文章挂到团队上，都要这份数据。
OpenAlex 一次批量取回（免费额度约 25 次查询），之后检索、挂团队全在本地、零网络。

**可重建**：删掉重跑 `python -m tools.library 检索 --建索引` 即可。存在 `paths.oa_index()`。

每篇一条：
    {doi, openalex, year, venue, abstract,
     authors: [{n: 名字, id: OpenAlex 短编号, c: 是否通讯, p: first/middle/last, inst: [单位名…]}]}

| 函数 | 干什么 |
|---|---|
| `build(on_progress=None)` | 全库取一遍、写索引（联网）|
| `add(pids)` | 只补这几篇（新收进库的），一次批量查询（联网）；取全文作业收尾时调 |
| `load()` | 读索引；没有就返回 None |
| `slim(work)` | OpenAlex work → 上面那条（纯函数，测试用）|
"""
import io
import json
import os
from datetime import datetime

from shared.kernel import catalog, paths

SELECT = 'id,doi,publication_year,authorships,primary_location,abstract_inverted_index'


def _sid(u):
    return (u or '').rsplit('/', 1)[-1]


def slim(w):
    from shared.adapters import openalex
    loc = w.get('primary_location') or {}
    src = (loc.get('source') or {}) if isinstance(loc, dict) else {}
    authors = []
    for a in w.get('authorships') or []:
        authors.append({'n': (a.get('author') or {}).get('display_name') or a.get('raw_author_name') or '',
                        'id': _sid((a.get('author') or {}).get('id')),
                        'c': bool(a.get('is_corresponding')),
                        'p': a.get('author_position') or '',
                        'inst': [i.get('display_name') for i in a.get('institutions') or [] if i.get('display_name')]})
    return {'doi': catalog.norm_doi(w.get('doi')), 'openalex': _sid(w.get('id')),
            'year': w.get('publication_year'), 'venue': src.get('display_name') or '',
            'abstract': openalex.restore_abstract(w.get('abstract_inverted_index'), limit=0),
            'authors': authors}


def build(on_progress=None):
    from shared.adapters import openalex
    pid_by_doi = {}
    for r in catalog.scan():
        d = catalog.norm_doi(r.get('doi'))
        if d:
            pid_by_doi[d] = r['id']
    works = openalex.works_by_dois(list(pid_by_doi), select=SELECT, on_progress=on_progress)
    papers = {}
    for w in works.values():
        s = slim(w)
        pid = pid_by_doi.get(s['doi'])
        if pid:
            papers[pid] = s
    out = {'说明': '每篇的作者 + 摘要（OpenAlex，tools.library.oaindex 生成，可重建）',
           'built_at': datetime.now().isoformat(timespec='seconds'),
           'n_catalog_doi': len(pid_by_doi), 'n_found': len(papers), 'papers': papers}
    p = paths.oa_index()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(out, io.open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    return out


def add(pids):
    """只补这几篇（新收进库的）→ 补上了几篇。索引里已有的跳过；OpenAlex 一次批量查询（≤50 篇一次）。

    2026-10-31 文献库应用加「导入」后：新收的文献卡片上没有作者和摘要，要等整库 `build` 一遍
    （约 25 次查询）才有。取全文作业收尾时调它，只查新的那几篇。
    """
    from shared.adapters import openalex
    index = load() or {'说明': '每篇的作者 + 摘要（OpenAlex，tools.library.oaindex 生成，可重建）', 'papers': {}}
    pid_by_doi = {}
    for pid in pids:
        d = catalog.norm_doi(catalog.read_meta(pid).get('doi'))
        if d and pid not in index['papers']:
            pid_by_doi[d] = pid
    if not pid_by_doi:
        return 0
    n = 0
    for w in openalex.works_by_dois(list(pid_by_doi), select=SELECT, allow_partial=True).values():
        s = slim(w)
        pid = pid_by_doi.get(s['doi'])
        if pid:
            index['papers'][pid] = s
            n += 1
    if n:
        index['updated_at'] = datetime.now().isoformat(timespec='seconds')
        index['n_found'] = len(index['papers'])
        p = paths.oa_index()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + '.tmp'
        json.dump(index, io.open(tmp, 'w', encoding='utf-8'), ensure_ascii=False)
        os.replace(tmp, p)          # 文献库应用随时在读，别让它读到写了一半的
    return n


def load():
    p = paths.oa_index()
    if not os.path.isfile(p):
        return None
    return json.load(io.open(p, encoding='utf-8'))
