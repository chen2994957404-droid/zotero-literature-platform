# -*- coding: utf-8 -*-
"""litsearch.session · 检索台账：一个研究问题的多轮检索 —— 搜了什么、找到什么、判了什么、搜全没有。

**为什么有它**（2026-09-24 用户定方向，规划见 `docs/reference/检索全面性_改造规划.md`）：
让 agent 多轮、全面地找文献。单个检索词搜不全，要「取结果 → 判 → 挖新词 → 再搜」。
没有台账时每次检索都是孤立的：第三轮就开始重复读看过的，也说不出搜全了没有。

用户定的原则：**工具只记账、递事实，取舍由 agent 和用户对话时决定**，不预设任何领域。
所以本模块只做与领域无关的四件事：

1. **记账**：每次检索 / 雪球落到同一个会话（第几轮、哪个渠道、检索式、全世界命中数），
   每篇记下被哪些渠道找到、第几轮首次出现；检索时据此标「新 / 见过 / 已判」
2. **记判断**：按 agent 和用户商定的判据**逐条**记（Ai2 Paper Finder 的做法：
   拆成小判断再合并，比整体判更准，弱模型也判得动）；只凭标题判的单列（踩坑 #188：Elsevier 大多没摘要）
3. **量覆盖**：每轮 × 每渠道新增的相关篇（饱和曲线，Wohlin 2014：一轮没有新的就停）；
   捕获–再捕获（Chapman 估计，Kastner 2009）—— **只拿「引用」对「文本（词面 + 语义）」算**，
   因为词面和语义两个渠道不独立，拿它们算会偏乐观；相对召回（给标准集时，Sampson 2006）
4. **挖新词**：已判相关的标题 + 摘要里相对其余结果显著多出来的词组（对数几率比 + 信息先验，
   Monroe, Colaresi & Quinn 2008），纯统计、不用模型、不预设词表 —— 替代「模型凭空补词」
   （模型写检索式召回偏低且不可复现：Wang 2023、SIGIR 2025 复评）

落盘：`state/searches/session_<名>.json`（可重建层：删了只丢历史）。不写 Zotero、不花钱。

对外接口：
    open_session(name, question='', criteria=None, scope_note='')   建 / 读 / 补充会话
    next_round(name)                            进入下一轮，返回新轮次号
    record(name, channel, items, term='', total=None, seed='', calls=1)
                                                记一次检索；返回每条的「记账前状态」
    state_of(name, items)                       只查状态不记账
    judge(name, judgments)                      批量记判断
    status(name, benchmark=None)                汇总：轮次、饱和曲线、渠道重叠、估计、相对召回
    mine_terms(name, k=30)                      挖新词 + 相关篇里常见的作者 / 期刊
    key_of(item)                                一篇在台账里的键（DOI；没有就用归一标题）
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

import io
import json
import math
import re
import time
from collections import Counter

from shared.domain.stopwords import ENGLISH_STOP_WORDS
from shared.kernel import paths

CHANNELS = ('keyword', 'semantic', 'cited_by', 'references', 'other')
_CITATION = ('cited_by', 'references')
_TEXT = ('keyword', 'semantic')

VERDICTS = ('relevant', 'partial', 'irrelevant', 'unsure')
_REL = ('relevant', 'partial')           # 统计「相关」时两档都算，partial 另行单列
BASES = ('abstract', 'title', 'fulltext')
CRITERION_MARKS = ('yes', 'partial', 'no', 'unknown')

# 判断的中文别名：agent 用中文写也认（它和用户说中文）
_VERDICT_ALIAS = {'相关': 'relevant', '部分': 'partial', '部分相关': 'partial', '不相关': 'irrelevant',
                  '没法判': 'unsure', '不确定': 'unsure', 'yes': 'relevant', 'no': 'irrelevant'}
_BASIS_ALIAS = {'摘要': 'abstract', '标题': 'title', '仅标题': 'title', '全文': 'fulltext'}
_MARK_ALIAS = {'是': 'yes', '部分': 'partial', '否': 'no', '不知道': 'unknown', True: 'yes', False: 'no'}


def _slug(name):
    s = re.sub(r'[^\w\-]+', '_', (name or '').strip())[:60].strip('_')
    if not s:
        raise ValueError('会话名不能为空')
    return s


def _path(name):
    return paths.search_record('session_' + _slug(name), create_dir=True)


def _load(name):
    try:
        return json.load(io.open(_path(name), encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _save(name, s):
    p = _path(name)
    tmp = p + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(s, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _norm_doi(d):
    d = (d or '').strip().lower()
    for pre in ('https://doi.org/', 'http://doi.org/', 'doi:'):
        if d.startswith(pre):
            d = d[len(pre):]
    return d


def _title_key(t):
    return 'title:' + re.sub(r'\W+', ' ', (t or '').lower()).strip()[:120]


def key_of(it):
    """一篇在台账里的键：DOI（小写、去前缀）；没有 DOI 用 `title:归一标题`。"""
    return _norm_doi(it.get('doi')) or _title_key(it.get('title'))


def _resolve(s, ref):
    """agent 给的引用（DOI / title: 键 / 带前缀的 DOI）→ 台账里的键；找不到返回 None。"""
    ref = str(ref or '').strip()
    if not ref:
        return None
    # title: 键再归一一次：agent 可能照原标题自己拼（带标点 / 大小写），不必逐字照抄台账里的键
    k = _title_key(ref[len('title:'):]) if ref.startswith('title:') else _norm_doi(ref)
    return k if k in s['works'] else None


def open_session(name, question='', criteria=None, scope_note=''):
    """建或读会话。已存在时：question 只在原来为空时写入；criteria 给了就**替换**（判据可以和用户商量后改）；
    scope_note 追加一条（范围约定的原话，后续轮次照着办）。"""
    s = _load(name)
    changed = False
    if s is None:
        s = {'name': _slug(name), 'question': question or '', 'criteria': [], 'scope_notes': [],
             'created': time.strftime('%Y-%m-%d %H:%M'), 'round': 1, 'searches': [], 'works': {}}
        changed = True
    s.setdefault('criteria', [])
    s.setdefault('scope_notes', [])
    if question and not s.get('question'):
        s['question'] = question
        changed = True
    if criteria is not None:
        crit = [str(c).strip() for c in (criteria if isinstance(criteria, (list, tuple)) else [criteria])
                if str(c).strip()]
        if crit != s['criteria']:
            s['criteria'] = crit
            changed = True
    if scope_note and scope_note.strip():
        s['scope_notes'].append({'round': s.get('round', 1), 'note': scope_note.strip()[:500],
                                 'time': time.strftime('%Y-%m-%d %H:%M')})
        changed = True
    if changed:
        _save(name, s)
    return s


def next_round(name):
    s = open_session(name)
    s['round'] = int(s.get('round') or 1) + 1
    _save(name, s)
    return s['round']


def _state(w):
    if w is None:
        return {'new': True}
    j = w.get('judgment') or {}
    return {'new': False, 'first_round': w.get('first_round'), 'verdict': j.get('verdict'),
            'channels': list(w.get('channels') or [])}


def state_of(name, items):
    """每条在台账里的状态（不记账）：[{'new': bool, 'first_round', 'verdict', 'channels'}]。"""
    s = open_session(name)
    return [_state(s['works'].get(key_of(it))) for it in items or []]


def record(name, channel, items, term='', total=None, seed='', calls=1):
    """记一次检索 / 雪球。`channel` ∈ CHANNELS（别的一律记成 other）。

    返回与 items 同序的「**记账前**」状态列表（同 `state_of`）—— 调用方据此标「新 / 见过 / 已判」。
    `calls` = 这次向外部服务发了几次请求（语义检索按年切片时 > 1），`status` 里累计成花销。
    """
    if channel not in CHANNELS:
        channel = 'other'
    s = open_session(name)
    rnd = int(s.get('round') or 1)
    before, new = [], 0
    for it in items or []:
        k = key_of(it)
        w = s['works'].get(k)
        before.append(_state(w))
        if w is None:
            w = s['works'][k] = {
                'doi': _norm_doi(it.get('doi')), 'title': it.get('title') or '', 'year': it.get('year'),
                'venue': it.get('venue') or '', 'first_author': it.get('first_author') or '',
                'abstract': (it.get('abstract') or '')[:1500], 'channels': [], 'first_round': rnd,
                'first_channel': channel, 'judgment': None}
            new += 1
        if channel not in w['channels']:
            w['channels'].append(channel)
        if not w.get('abstract') and it.get('abstract'):
            w['abstract'] = it['abstract'][:1500]
    s['searches'].append({'round': rnd, 'channel': channel, 'term': (term or '')[:300], 'seed': seed,
                          'total': total, 'returned': len(items or []), 'new': new,
                          'calls': int(calls or 0), 'time': time.strftime('%Y-%m-%d %H:%M')})
    _save(name, s)
    return before


def _norm_marks(d):
    out = {}
    for c, m in (d or {}).items():
        m = _MARK_ALIAS.get(m, m)
        m = str(m).strip().lower() if not isinstance(m, str) else m.strip().lower()
        m = _MARK_ALIAS.get(m, m)
        out[str(c).strip()[:120]] = m if m in CRITERION_MARKS else 'unknown'
    return out


def judge(name, judgments):
    """批量记判断。每条：`{doi, verdict, criteria?: {判据: yes/partial/no/unknown}, basis?, reason?}`。

    verdict ∈ relevant / partial / irrelevant / unsure（中文「相关 / 部分 / 不相关 / 没法判」也认）；
    basis ∈ abstract / title / fulltext（默认：有摘要记 abstract，没有记 title）。
    返回 `{'judged': n, 'unknown': [台账里没有的引用], 'bad': [verdict 认不出的]}`。
    """
    s = open_session(name)
    if isinstance(judgments, dict):
        judgments = [judgments]
    judged, unknown, bad = 0, [], []
    for j in judgments or []:
        ref = j.get('doi') or j.get('key') or ''
        k = _resolve(s, ref)
        if k is None:
            unknown.append(ref)
            continue
        v = str(j.get('verdict') or '').strip()
        v = _VERDICT_ALIAS.get(v, _VERDICT_ALIAS.get(v.lower(), v.lower()))
        if v not in VERDICTS:
            bad.append(ref)
            continue
        w = s['works'][k]
        basis = str(j.get('basis') or '').strip()
        basis = _BASIS_ALIAS.get(basis, basis.lower())
        if basis not in BASES:
            basis = 'abstract' if w.get('abstract') else 'title'
        w['judgment'] = {'verdict': v, 'criteria': _norm_marks(j.get('criteria')), 'basis': basis,
                         'reason': str(j.get('reason') or '')[:300], 'round': s.get('round', 1)}
        judged += 1
    _save(name, s)
    return {'judged': judged, 'unknown': unknown, 'bad': bad}


def chapman(n1, n2, m):
    """捕获–再捕获的 Chapman 估计：两个独立渠道各抓到 n1、n2 篇，重叠 m 篇 → 总量估计。"""
    return (n1 + 1) * (n2 + 1) / (m + 1) - 1


def _verdict(w):
    return (w.get('judgment') or {}).get('verdict')


def status(name, benchmark=None):
    """汇总台账。返回 dict（MCP 面负责渲染成人话）。"""
    s = open_session(name)
    works = s['works']
    rel = {k: w for k, w in works.items() if _verdict(w) in _REL}
    cur = int(s.get('round') or 1)
    rounds = sorted({int(w.get('first_round') or 1) for w in works.values()} | {cur})
    curve = []
    for r in rounds:
        row = {'round': r, 'new_works': 0, 'new_relevant': 0, 'by_channel': {}}
        for w in works.values():
            if w.get('first_round') != r:
                continue
            ch = w.get('first_channel') or (w.get('channels') or ['other'])[0]
            c = row['by_channel'].setdefault(ch, {'new': 0, 'relevant': 0})
            c['new'] += 1
            row['new_works'] += 1
            if _verdict(w) in _REL:
                c['relevant'] += 1
                row['new_relevant'] += 1
        curve.append(row)
    # 各渠道「找到的相关篇」（一篇可以被多个渠道找到）→ 各渠道独有的贡献
    by_ch = {ch: {k for k, w in rel.items() if ch in (w.get('channels') or [])} for ch in CHANNELS}
    only = {ch: len(ks - set().union(*(v for c2, v in by_ch.items() if c2 != ch))) for ch, ks in by_ch.items()}
    counts = Counter(_verdict(w) or 'unjudged' for w in works.values())
    title_only = sum(1 for w in rel.values() if (w.get('judgment') or {}).get('basis') == 'title')
    out = {
        'name': s['name'], 'question': s.get('question', ''), 'criteria': s.get('criteria', []),
        'scope_notes': [n['note'] for n in s.get('scope_notes', [])], 'round': cur,
        'n_searches': len(s['searches']), 'n_calls': sum(int(q.get('calls') or 0) for q in s['searches']),
        'n_works': len(works), 'verdicts': dict(counts), 'n_relevant': len(rel),
        'relevant_title_only': title_only,
        'no_abstract': sum(1 for w in works.values() if not w.get('abstract')),
        'curve': curve,
        'relevant_by_channel': {ch: len(v) for ch, v in by_ch.items() if v},
        'relevant_only_by_channel': {ch: n for ch, n in only.items() if n},
    }
    txt = {k for k, w in rel.items() if set(w.get('channels') or []) & set(_TEXT)}
    cit = {k for k, w in rel.items() if set(w.get('channels') or []) & set(_CITATION)}
    if txt and cit:
        m = len(txt & cit)
        est = chapman(len(txt), len(cit), m)
        found = len(txt | cit)
        out['capture_recapture'] = {
            'text': len(txt), 'citation': len(cit), 'both': m,
            'estimated_total': round(est, 1),
            'estimated_coverage': round(min(1.0, found / est), 3) if est > 0 else None,
            'reliable': m >= 3,
            'note': '文本渠道（词面+语义）对引用渠道；前提是两者大致独立。重叠少于 3 篇时估计不可靠，只当参考'}
    if benchmark:
        bench = {_norm_doi(d) for d in benchmark if d and _norm_doi(d)}
        found = bench & set(works)
        found_rel = bench & set(rel)
        out['relative_recall'] = {
            'benchmark': len(bench), 'found_anywhere': len(found), 'judged_relevant': len(found_rel),
            'recall_found': round(len(found) / len(bench), 3) if bench else None,
            'recall_relevant': round(len(found_rel) / len(bench), 3) if bench else None,
            'missing': sorted(bench - found)[:50]}
    return out


# ── 新词挖掘：带信息先验的对数几率比（Monroe, Colaresi & Quinn 2008）────────────
_TOKEN = re.compile(r"[a-z][a-z0-9\-']+")
_STOP = ENGLISH_STOP_WORDS      # 现成停用词表；学术套话（study / results…）两边都常见，对数几率比自己会压下去


def _grams(text, nmax=3):
    toks = _TOKEN.findall((text or '').lower())
    out = []
    for n in range(1, nmax + 1):
        for i in range(len(toks) - n + 1):
            g = toks[i:i + n]
            if g[0] in _STOP or g[-1] in _STOP:
                continue
            out.append(' '.join(g))
    return out


def log_odds(fg, bg, prior_scale=0.01):
    """对数几率比 + 信息先验的 z 值：前景（相关）相对背景（其余）多出来的词组。返回 [(词组, z)] 降序。"""
    prior = Counter()
    for c in (fg, bg):
        prior.update(c)
    a0 = sum(prior.values()) * prior_scale
    n1, n2 = sum(fg.values()), sum(bg.values())
    out = []
    for w in fg:
        a = prior[w] * prior_scale or 1e-3
        y1, y2 = fg[w], bg.get(w, 0)
        l1 = math.log((y1 + a) / (n1 + a0 - y1 - a))
        l2 = math.log((y2 + a) / max(n2 + a0 - y2 - a, 1e-9))
        var = 1.0 / (y1 + a) + 1.0 / (y2 + a)
        out.append((w, (l1 - l2) / math.sqrt(var)))
    return sorted(out, key=lambda x: -x[1])


def mine_terms(name, k=30, min_docs=2):
    """已判相关（含部分相关）的标题 + 摘要 vs 其余检索结果 → 显著多出来的词组，排除已搜过的词。

    返回 `{'terms': 混排前 k, 'phrases': 词组, 'words': 单词, 'authors': [(一作, 篇数)], 'venues': [(期刊, 篇数)], 'n_relevant': n}`，
    每个词条 `{term, z, docs}`。
    还没判出相关的时候 terms 为空（没有前景就没有「多出来」）—— 如实返回，不拿全体频次冒充。
    """
    s = open_session(name)
    rel = [w for w in s['works'].values() if _verdict(w) in _REL]
    rest = [w for w in s['works'].values() if _verdict(w) not in _REL]
    fg, bg, df = Counter(), Counter(), Counter()
    for w in rel:
        gs = _grams((w.get('title') or '') + '. ' + (w.get('abstract') or ''))
        fg.update(gs)
        df.update(set(gs))
    for w in rest:
        bg.update(_grams((w.get('title') or '') + '. ' + (w.get('abstract') or '')))
    used = ' '.join((q.get('term') or '').lower() for q in s['searches'])
    keep = []
    if fg:
        ranked = [(g, z) for g, z in log_odds(fg, bg) if df[g] >= min_docs and g not in used]
        # 同一词组的子串只留更长的那个（「shear stiffening gel」在就不再列「stiffening gel」）
        for g, z in ranked:
            if any(g in h and g != h for h, _ in keep):
                continue
            keep.append((g, z))
            if len(keep) >= 2 * k:
                break
    rows = [{'term': g, 'z': round(z, 2), 'docs': df[g]} for g, z in keep]
    # 词组与单词分开给（2026-09-26 实测：单词榜会被 networks / design 这类泛词占满，
    # 而下一轮检索真正用得上的是词组）。各自按 z 排，词组最多 k 个、单词最多 k//2 个。
    phrases = [r for r in rows if ' ' in r['term']][:k]
    words = [r for r in rows if ' ' not in r['term']][:max(1, k // 2)]
    authors = Counter(w.get('first_author') for w in rel if w.get('first_author'))
    venues = Counter(w.get('venue') for w in rel if w.get('venue'))
    return {'terms': rows[:k], 'phrases': phrases, 'words': words,
            'authors': [a for a in authors.most_common(10) if a[1] >= 2],
            'venues': [v for v in venues.most_common(10) if v[1] >= 2],
            'n_relevant': len(rel)}
