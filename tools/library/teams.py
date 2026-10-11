# -*- coding: utf-8 -*-
"""tools.library.teams · 把证据库里的文章挂到研究团队上。

**名单是人工查证的**（`paths.teams()`，2026-10-11 用户定：不做自动化流程，Claude 查证、用户纠正）。
本模块只做「名单 × 每篇文章的作者」这一步机械的对照，不猜谁是大导。

挂法（照 docs/reference/文献管理_调研_2026-10-08.md 第十节的结论）：
1. 先看**末位作者**：他是通讯（或这篇没标通讯）就以他为准 ——
   在名单里 → 主组；不在名单里 → 这篇是名单外团队的，名单里的共同通讯只算「合作」。
   （Hawker / Matyjaszewski 那种「大牛当共同通讯」不会再把别人的文章吸进自己组。）
2. 末位作者不是通讯 → 按通讯作者找。
3. 小导的文章归他所在的组；**已独立的人**（alumni）`since` 年起不再算老组，之前的照算。
4. 一篇可以挂多个组：一个主组 + 若干合作组。

作者身份用 OpenAlex 编号（名单里每人收了同名碎片编号）。取作者走 `shared.adapters.openalex`，
结果缓存进 `paths.team_links()`（可重建），页面和命令行都读缓存、零网络。

| 函数 | 干什么 |
|---|---|
| `load_roster()` | 读名单 |
| `person_index(roster)` | OpenAlex 编号 → [(团队序号, 角色, since)] |
| `link_work(work, index)` | 一篇 OpenAlex work → {primary, others, via} |
| `build(on_progress=None)` | 全库取作者、挂组、写缓存（联网，免费额度约 25 次查询）|
| `load_links()` | 读缓存 |
| `summary(roster, links)` | 每个团队挂了几篇 |
| `render_list` / `render_team` | 渲染给人看 |
"""
import io
import json
import os
from datetime import datetime

from shared.kernel import catalog, paths

SELECT = 'id,doi,publication_year,authorships'


def _sid(u):
    return (u or '').rsplit('/', 1)[-1]


def load_roster():
    p = paths.teams()
    if not os.path.isfile(p):
        return {'teams': []}
    return json.load(io.open(p, encoding='utf-8'))


def person_index(roster):
    """OpenAlex 编号 → [(团队序号, 角色, since)]。角色：大导 / 小导 / 已独立。"""
    idx = {}
    for i, t in enumerate(roster.get('teams', [])):
        groups = (([t['leader']] if t.get('leader') else [], '大导'),
                  (t.get('members', []), '小导'),
                  (t.get('alumni', []), '已独立'))
        for people, role in groups:
            for p in people:
                for oa in p.get('openalex', []):
                    idx.setdefault(oa, []).append((i, role, p.get('since')))
    return idx


def _teams_of(aid, year, idx):
    out = []
    for i, role, since in idx.get(aid, []):
        if role == '已独立' and since and year and year >= since:
            continue                       # 独立之后的文章不再算老组
        out.append(i)
    return out


def link_work(work, idx):
    """一篇 work → {'primary': 团队序号或 None, 'others': [...], 'via': 作者名}。

    primary 为 None 且 others 为空 = 这篇跟名单上的团队都没关系。"""
    au = work.get('authorships') or []
    year = work.get('publication_year')
    if not au:
        return {'primary': None, 'others': [], 'via': ''}
    corr = [a for a in au if a.get('is_corresponding')]
    last = au[-1]
    last_rules = last.get('is_corresponding') or not corr
    primary, via = None, ''
    if last_rules:
        ts = _teams_of(_sid(last['author'].get('id')), year, idx)
        if ts:
            primary, via = ts[0], last['author'].get('display_name', '')
    else:
        for a in corr:
            ts = _teams_of(_sid(a['author'].get('id')), year, idx)
            if ts:
                primary, via = ts[0], a['author'].get('display_name', '')
                break
    others = []
    for a in corr + [last]:
        for t in _teams_of(_sid(a['author'].get('id')), year, idx):
            if t != primary and t not in others:
                others.append(t)
    return {'primary': primary, 'others': others, 'via': via}


def build(on_progress=None):
    """全库取作者 → 挂组 → 写 `paths.team_links()`。返回缓存内容。"""
    from shared.adapters import openalex
    roster = load_roster()
    idx = person_index(roster)
    pid_by_doi = {}
    for r in catalog.scan():
        d = catalog.norm_doi(r.get('doi'))
        if d:
            pid_by_doi[d] = r['id']
    works = openalex.works_by_dois(list(pid_by_doi), select=SELECT, on_progress=on_progress)
    papers = {}
    for w in works.values():
        d = catalog.norm_doi(w.get('doi'))
        pid = pid_by_doi.get(d)
        if not pid:
            continue
        lk = link_work(w, idx)
        papers[pid] = {'doi': d, 'year': w.get('publication_year'), **lk}
    out = {'说明': '文章 → 研究团队（tools.library.teams 生成，可重建；团队序号对应 teams.json 里 teams 的顺序）',
           'built_at': datetime.now().isoformat(timespec='seconds'),
           'roster_updated': roster.get('updated'),
           'n_catalog_doi': len(pid_by_doi), 'n_openalex': len(works), 'papers': papers}
    p = paths.team_links()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(out, io.open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return out


def load_links():
    p = paths.team_links()
    if not os.path.isfile(p):
        return None
    return json.load(io.open(p, encoding='utf-8'))


def summary(roster, links):
    """[(团队序号, 主组篇数, 合作篇数)]，按主组篇数降序。"""
    main, coop = {}, {}
    for v in (links or {}).get('papers', {}).values():
        if v['primary'] is not None:
            main[v['primary']] = main.get(v['primary'], 0) + 1
        for t in v['others']:
            coop[t] = coop.get(t, 0) + 1
    rows = [(i, main.get(i, 0), coop.get(i, 0)) for i in range(len(roster.get('teams', [])))]
    return sorted(rows, key=lambda r: (-r[1], -r[2]))


def _label(p):
    zh = p.get('name_zh') or ''
    return f"{zh} {p['name']}".strip() if zh else p['name']


def render_list(roster, links):
    if links is None:
        return '还没挂过：先跑 `python -m tools.library 团队 --重建`（取一次 OpenAlex 作者，免费额度）'
    ps = links['papers']
    n_main = sum(1 for v in ps.values() if v['primary'] is not None)
    n_any = sum(1 for v in ps.values() if v['primary'] is not None or v['others'])
    lines = [f"团队 {len(roster['teams'])} 个 · 证据库 {len(ps)} 篇里挂上主组 {n_main} 篇、"
             f"跟名单团队有关（含合作）{n_any} 篇 · 缓存 {links['built_at']}", '']
    for i, m, c in summary(roster, links):
        t = roster['teams'][i]
        extra = f"（另有合作 {c}）" if c else ''
        lines.append(f"{m:>4} 篇{extra}  {_label(t['leader'])} · {t.get('inst', '')}")
    return '\n'.join(lines)


def find_team(roster, q):
    q = (q or '').lower().replace(' ', '')
    for i, t in enumerate(roster.get('teams', [])):
        names = [t['leader']['name'], t['leader'].get('name_zh', '')]
        if any(q and q in n.lower().replace(' ', '') for n in names if n):
            return i
    return None


def render_team(roster, links, i):
    t = roster['teams'][i]
    mark = lambda p: '✅' if p.get('status') == 'verified' else '🔎'
    lines = [f"# {_label(t['leader'])} · {t.get('inst', '')} {mark(t['leader'])}"]
    for p in t.get('members', []):
        lines.append(f"- 小导 {mark(p)} {_label(p)}" + (f" —— {p['note']}" if p.get('note') else ''))
    for p in t.get('alumni', []):
        lines.append(f"- 已独立 {mark(p)} {_label(p)}" + (f"（{p['since']} 起）" if p.get('since') else '')
                     + (f" → {p['now']}" if p.get('now') else ''))
    for p in t.get('pending', []):
        lines.append(f"- 待查 {_label(p)}" + (f" —— {p['note']}" if p.get('note') else ''))
    for n in t.get('notes', []):
        lines.append(f"- 注：{n}")
    if links:
        main = sorted(((v['year'] or 0, pid, v) for pid, v in links['papers'].items() if v['primary'] == i),
                      reverse=True)
        coop = sorted(((v['year'] or 0, pid, v) for pid, v in links['papers'].items() if i in v['others']),
                      reverse=True)
        titles = {r['id']: r.get('title') or '' for r in catalog.scan()}
        lines += ['', f"## 本组文章 {len(main)} 篇"]
        lines += [f"- {y or '?'} · {titles.get(pid, '')[:90]} · {pid}（{v['via']}）" for y, pid, v in main]
        if coop:
            lines += ['', f"## 合作文章 {len(coop)} 篇"]
            lines += [f"- {y or '?'} · {titles.get(pid, '')[:90]} · {pid}" for y, pid, v in coop]
    return '\n'.join(lines)
