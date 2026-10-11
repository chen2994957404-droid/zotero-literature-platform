# -*- coding: utf-8 -*-
"""tools.library.dbsearch · 检索证据库：DOI / 标题词 / 作者 / 通讯作者 / 团队 / 年份 / 期刊 / 手上有什么。

**全本地、零网络**：目录卡（catalog）+ 作者摘要索引（oaindex）+ 团队对照（teams）。
一千多篇现扫是毫秒级，不另建全文索引（同 catalog 的判据：索引和文件不同步的 bug 比省的时间贵）。

匹配规则：
- 输入像 DOI（含 `10.xxxx/`）→ 按 DOI 精确找；
- 否则把输入拆成词，**每个词都要命中**（标题 / 作者 / 期刊，勾了 abstract 再加摘要），
  不分大小写、不管连字符与重音（Shu-Hong = Shuhong）；
- 人名不管顺序：「Wu Peiyi」「Peiyi Wu」都能找到；中文名经团队名单换成编号再找（「武培怡」）。
排序：标题命中 > 作者命中 > 期刊 > 摘要，同分按年份新的在前。

| 函数 | 干什么 |
|---|---|
| `find(q='', corr='', author='', team='', year_from=None, year_to=None, journal='', has=(), abstract=False, limit=30)` | 检索，返回结果列表 |
| `render(rows, total)` | 渲染给人看 |
| `detail(pid)` | 一篇的完整卡片（作者 / 单位 / 摘要 / 团队 / 文件）|
| `norm(text)` / `tokens(text)` / `is_doi(text)` | 纯函数（测试用）|
"""
import os
import re
import unicodedata

from shared.kernel import catalog

HAS = {'正文': 'pdf', 'pdf': 'pdf', 'si': 'si', 'SI': 'si', '精读': 'summary', 'summary': 'summary',
       '解析': 'fulltext', 'fulltext': 'fulltext', '结构化': 'structured', 'structured': 'structured'}
_DOI = re.compile(r'10\.\d{4,9}/\S+', re.I)


def norm(text):
    t = text or ''
    if not re.search(r'[一-鿿]', t):          # 中文不动；西文去重音（Ruixue = Ruìxué）
        t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode()
    t = t.lower()
    t = re.sub(r'[‐-―\-‐_/]', '', t)       # 连字符去掉：Shu-Hong = Shuhong
    return re.sub(r'\s+', ' ', t).strip()


def tokens(text):
    return [w for w in re.split(r'[\s,;，；]+', norm(text)) if w]


def is_doi(text):
    return bool(_DOI.search(text or ''))


def _name_hit(qtoks, name):
    """人名：查询词全部出现在名字的词里（不管顺序）；单个词也可以是名字的一部分。"""
    ntoks = tokens(name)
    joined = ''.join(ntoks)
    return all(any(q == t or (len(q) >= 3 and q in t) for t in ntoks) or (len(q) >= 4 and q in joined)
               for q in qtoks)


def _zh_ids(name, roster):
    """中文名 → 名单里这个人的 OpenAlex 编号。"""
    if not re.search(r'[一-鿿]', name or ''):
        return set()
    out = set()
    for t in roster.get('teams', []):
        for p in [t['leader']] + t.get('members', []) + t.get('alumni', []) + t.get('pending', []):
            if p.get('name_zh') and name in p['name_zh']:
                out |= set(p.get('openalex', []))
    return out


def _person_match(q, authors, roster):
    """q（拼音或中文）是否命中 authors 里的某个人。"""
    ids = _zh_ids(q, roster)
    if ids:
        return any(a['id'] in ids for a in authors)
    qt = tokens(q)
    return bool(qt) and any(_name_hit(qt, a['n']) for a in authors)


def find(q='', corr='', author='', team='', year_from=None, year_to=None, journal='',
         has=(), abstract=False, limit=30):
    from tools.library import oaindex, teams
    index = (oaindex.load() or {}).get('papers', {})
    roster = teams.load_roster()
    links = (teams.load_links() or {}).get('papers', {})
    team_i = teams.find_team(roster, team) if team else None
    if team and team_i is None:
        return [], 0
    need = [HAS.get(h) or h for h in has if h]
    q = (q or '').strip()
    m = _DOI.search(q)
    doi_q = catalog.norm_doi(m.group(0)) if m else ''
    qtoks = [] if doi_q else tokens(q)
    rows = []
    for r in catalog.scan():
        pid = r['id']
        e = index.get(pid, {})
        authors = e.get('authors') or []
        year = r.get('year') or e.get('year')
        venue = r.get('journal') or e.get('venue') or ''
        if doi_q and catalog.norm_doi(r.get('doi')) != doi_q:
            continue
        if year_from and (not year or int(year) < int(year_from)):
            continue
        if year_to and (not year or int(year) > int(year_to)):
            continue
        if journal and norm(journal) not in norm(venue):
            continue
        if any(not r.get(k) for k in need):
            continue
        if corr:
            cs = [a for a in authors if a['c']] or ([authors[-1]] if authors else [])
            if not _person_match(corr, cs, roster):
                continue
        if author and not _person_match(author, authors, roster):
            continue
        lk = links.get(pid) or {}
        if team_i is not None and lk.get('primary') != team_i and team_i not in (lk.get('others') or []):
            continue
        score = 0
        if qtoks:
            t, v = norm(r.get('title')), norm(venue)
            names = ' '.join(norm(a['n']) for a in authors)
            ab = norm(e.get('abstract')) if abstract else ''
            ok = True
            for w in qtoks:
                if w in t:
                    score += 10
                elif w in names:
                    score += 6
                elif w in v:
                    score += 3
                elif ab and w in ab:
                    score += 1
                else:
                    ok = False
                    break
            if not ok:
                continue
        rows.append((score, year or 0, r, e, lk))
    rows.sort(key=lambda x: (-x[0], -int(x[1] or 0)))
    out = []
    for score, year, r, e, lk in rows[:limit]:
        authors = e.get('authors') or []
        cs = [a['n'] for a in authors if a['c']] or ([authors[-1]['n']] if authors else [])
        tm = lk.get('primary')
        out.append({'id': r['id'], 'title': ' '.join((r.get('title') or '').split()), 'year': year or None,
                    'journal': r.get('journal') or e.get('venue') or '', 'doi': r.get('doi') or '',
                    'corr': cs, 'n_authors': len(authors),
                    'team': _team_label(roster, tm) if tm is not None else '',
                    'coop': [_team_label(roster, i) for i in (lk.get('others') or [])],
                    'has': {k: bool(r.get(k)) for k in ('pdf', 'si', 'fulltext', 'summary', 'structured')}})
    return out, len(rows)


def _team_label(roster, i):
    p = roster['teams'][i]['leader']
    return p.get('name_zh') or p['name']


def render(rows, total):
    if not rows:
        return '没找到。'
    lines = [f'共 {total} 篇' + (f'，列前 {len(rows)}' if total > len(rows) else '')]
    for r in rows:
        tags = ''.join(f'[{n}]' for k, n in (('pdf', '正文'), ('si', 'SI'), ('summary', '精读')) if r['has'][k])
        team = f" · 组：{r['team']}" if r['team'] else ''
        coop = f"（合作：{'、'.join(r['coop'])}）" if r['coop'] else ''
        lines.append(f"\n{r['year'] or '?'} · {r['title'][:110]}\n"
                     f"   {r['journal']} · 通讯：{', '.join(r['corr']) or '?'}{team}{coop} {tags}\n"
                     f"   {r['doi'] or ''} · {r['id']}")
    return '\n'.join(lines)


def detail(pid):
    """一篇的完整卡片：目录卡 + 全部作者（通讯 / 单位）+ 摘要 + 团队 + 手上有哪些文件。找不到返回 None。"""
    from shared.kernel import paths
    from tools.library import oaindex, teams
    try:
        r = catalog.record(pid)
    except paths.BadKeyError:
        return None
    if not (r.get('title') or r.get('doi') or r.get('pdf')):
        return None
    e = ((oaindex.load() or {}).get('papers') or {}).get(r['id'], {})
    roster = teams.load_roster()
    lk = ((teams.load_links() or {}).get('papers') or {}).get(r['id']) or {}
    files = {'pdf': os.path.isfile(paths.local_pdf(r['id'])),
             'si': bool(paths.find_local_si(r['id'])),
             'summary': os.path.isfile(paths.summary(r['id'])),
             'si_summary': os.path.isfile(paths.si_summary(r['id'])),
             'summary_full': os.path.isfile(paths.summary_full(r['id']))}
    return {'id': r['id'], 'title': ' '.join((r.get('title') or '').split()), 'doi': r.get('doi') or '',
            'year': r.get('year') or e.get('year'), 'journal': r.get('journal') or e.get('venue') or '',
            'authors': e.get('authors') or [], 'abstract': e.get('abstract') or '',
            'team': _team_label(roster, lk['primary']) if lk.get('primary') is not None else '',
            'coop': [_team_label(roster, i) for i in (lk.get('others') or [])],
            'has': {k: bool(r.get(k)) for k in ('pdf', 'si', 'fulltext', 'summary', 'structured')},
            'files': files, 'in_zotero': bool(r.get('in_zotero'))}
