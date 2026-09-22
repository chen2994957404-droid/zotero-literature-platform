# -*- coding: utf-8 -*-
"""单元拆解第 2 步（2026-09-20）：从**英文原文**拆九类单元，再算范文的单元有几成能在原文单元里找到对应。

第 1 步（`units.py`）从范文反推出「精读由哪些单元组成」；这一步反过来问：**只看原文，这些单元抽得出来吗？**
抽得出来 → 「原文 → 单元 → 精读」这条路成立，而且每类单元各自可以换小模型；抽不出来的那几类才是真正难的地方。
方法是 Pyramid 那套：范文单元当标尺，原文单元当候选，一条一条配。

拆：原文按骨架切成小片（摘要 / 各节段落 ≤1500 字符 / 每条图注 / 每张表 / SI 合成段），一片一次调用，
     九类 = 第 1 步复核后的分类法（fact 只留带数字的、加 attribute 与 method、cause 定义为「为什么」）。
配：fact 按数值（norm 后相等）；entity 按缩写 / 拉丁名；panel 按图号 + 子图；
     其余（attribute / action / method / claim / role / cause）用 bge-m3 向量（跨语言）取同类或近类里最相似的一条，
     相似度过线算覆盖 —— 线是多少先量分布再定，报告里把四分位一起给出来。

产物：data/state/unit_study/<tag>/<pid>.src.json（原文单元）+ coverage.json + coverage.md。
用法：python -m tools.deepread --原文单元 --篇数 10 --本地 --tag u1
      python -m tools.deepread --单元覆盖 u1
"""
import io
import json
import math
import os
import re
import time

from shared.kernel import paths, prompts
from shared.domain.schema import outline as _ol
from shared.domain import numcheck as _nums
from tools.deepread.evals import units as U

PROMPT = 'units_src@v1'
TYPES = ('entity', 'fact', 'attribute', 'action', 'method', 'panel', 'claim', 'role', 'cause')
CHUNK = 1500
CAP_SI = 16000
NUM_CTX = 8192
SIM_LINE = 0.72          # 语义配对的覆盖线（先按这个报，报告里同时给分布）
NEAR = {'attribute': ('attribute', 'claim', 'fact'), 'claim': ('claim', 'attribute', 'cause'),
        'cause': ('cause', 'claim', 'role'), 'role': ('role', 'cause', 'attribute'),
        'action': ('action', 'method'), 'method': ('method', 'action')}


# ── 切片 ─────────────────────────────────────────────────────────────

def _chunks(text, size=CHUNK):
    paras = [p.strip() for p in re.split(r'\n\s*\n', text or '') if p.strip()]
    out, buf, used = [], [], 0
    for p in paras:
        if buf and used + len(p) > size:
            out.append('\n\n'.join(buf))
            buf, used = [], 0
        buf.append(p[:size])
        used += len(p)
    if buf:
        out.append('\n\n'.join(buf))
    return out


def pieces(md, outline, si_md=''):
    """原文 → [(kind, hint, text, pos)]。kind 是骨架节类或 caption/table/si；pos 是在全文的位置 0–1。"""
    out = []
    n = max(1, len(md))
    caps = [(f['start'], f['end']) for f in outline.get('figures') or []]
    for s in outline.get('sections') or []:
        if s['kind'] == _ol.NONBODY:
            continue
        text = _ol.section_text(md, outline, s['id'], with_subsections=False)
        # 图注区间从段落里挖掉（单独作为 caption 片）
        for a, b in caps:
            if s['start'] <= a < s['end']:
                seg = md[a:b]
                text = text.replace(seg, '')
        for c in _chunks(text):
            out.append((s['kind'], '%s section' % s['kind'], c, round(s['start'] / n, 3)))
    for f in outline.get('figures') or []:
        t = _ol.section_text(md, outline, f['id']).strip()
        if t:
            out.append(('caption', 'Figure caption (%s)' % f.get('ref', ''), t[:3000], round(f['start'] / n, 3)))
    for t in outline.get('tables') or []:
        html = _ol.section_text(md, outline, t['id']).strip()
        if html:
            out.append(('table', 'Table (%s) %s' % (t.get('ref', ''), t.get('caption', '')), html[:3000], round(t['start'] / n, 3)))
    if si_md:
        si_ol = _ol.build_outline(si_md)
        txt = ''
        for s in si_ol.get('sections') or []:
            if s['kind'] in (_ol.SYNTHESIS, _ol.METHODS):
                txt += _ol.section_text(si_md, si_ol, s['id'], with_subsections=False) + '\n\n'
        if len(txt) < 800:
            txt = _ol.scan.clean_body(si_md)
        for c in _chunks(txt[:CAP_SI]):
            out.append(('si', 'Supporting information (synthesis / methods)', c, None))
    return out


# ── 拆 ───────────────────────────────────────────────────────────────

def split_units(chat_json, hint, text, local=True, log=print):
    sysp = prompts.load('deepread', PROMPT)
    user = 'Passage type: %s\n\n%s' % (hint, text)
    try:
        if local:
            d = chat_json(sysp, user, provider='ollama', temperature=0.0, num_ctx=NUM_CTX) or {}
        else:
            d = chat_json(sysp, user, purpose='REVIEW', temperature=0.1) or {}
    except Exception as e:
        log('  拆解调用失败：%s' % str(e)[:80])
        return [], True
    units = []
    for u in (d.get('units') or []) if isinstance(d, dict) else []:
        if isinstance(u, dict) and str(u.get('type') or '').strip().lower() in TYPES:
            u = {k: (str(v) if not isinstance(v, (list, dict)) else v) for k, v in u.items()}
            u['type'] = u['type'].strip().lower()
            units.append(u)
    return units, False


def run_one(pid, chat_json, local=True, log=print):
    md = io.open(paths.fulltext(pid), encoding='utf-8').read()
    sp = paths.si_fulltext(pid)
    si = io.open(sp, encoding='utf-8').read() if os.path.exists(sp) else ''
    outline = _ol.build_outline(md)
    ps = pieces(md, outline, si)
    units, failed = [], 0
    for i, (kind, hint, text, pos) in enumerate(ps):
        us, bad = split_units(chat_json, hint, text, local, log)
        failed += bad
        for u in us:
            u['piece'] = i
            u['kind'] = kind
            u['pos'] = pos
        units += us
        log('  [%d/%d] %s %d 字符 → %d 条' % (i + 1, len(ps), kind, len(text), len(us)))
    return {'pid': pid, 'n_pieces': len(ps), 'src_chars': len(md), 'si_chars': len(si), 'failed_pieces': failed, 'units': units}


def run(keys, chat_json, tag='u1', local=True, log=print):
    out_dir = paths.unit_study_dir(tag)
    os.makedirs(out_dir, exist_ok=True)
    done = []
    for i, pid in enumerate(keys, 1):
        f = os.path.join(out_dir, pid + '.src.json')
        if os.path.exists(f):
            log('[%d/%d] %s 已有，跳过' % (i, len(keys), pid))
            done.append(pid)
            continue
        if not os.path.exists(paths.fulltext(pid)):
            log('[%d/%d] %s 缺全文，跳过' % (i, len(keys), pid))
            continue
        log('[%d/%d] %s' % (i, len(keys), pid))
        r = run_one(pid, chat_json, local, log)
        json.dump(r, io.open(f, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        done.append(pid)
    return done


# ── 配对与覆盖 ───────────────────────────────────────────────────────

_METHOD_VERB = re.compile(r'^(进行|利用|采用|通过|借助|开展|测试|表征|计算|测量|观察|使用|运用|评估|分析|记录|检测|模拟)')
_METHOD_WORD = re.compile(r'(测试|表征|显微镜|光谱|XPS|SEM|TEM|AFM|DSC|TGA|FTIR|NMR|XRD|流变|拉伸|模拟|阻抗|色谱|GPC|DMA|接触角|剥离|剪切|循环)')
_DIGIT = re.compile(r'\d')


def refine_ref(u):
    """第 1 步的七类 → 九类（复核后的规则）：没数字的 fact 是 attribute；表征手段类 action 是 method。"""
    t = u['type']
    if t == 'fact' and not _DIGIT.search(str(u.get('value', '')) + str(u.get('unit', ''))):
        return 'attribute'
    if t == 'action':
        a = str(u.get('action', ''))
        mats = ' '.join(str(x) for x in (u.get('materials') or []))
        if _METHOD_VERB.match(a) or _METHOD_WORD.search(a + mats):
            return 'method'
    return t


def text_of(u):
    return ' ; '.join('%s: %s' % (k, v if not isinstance(v, list) else ', '.join(map(str, v)))
                      for k, v in u.items()
                      if k not in ('type', 'col', 'para', 'len', 'loc', 'src', 'piece', 'kind', 'pos') and v)


def _nums_of(u):
    s = ' '.join(str(u.get(k, '')) for k in ('value', 'amounts', 'conditions', 'key_value'))
    return {_nums.norm(x) for x in re.findall(r'\d+(?:\.\d+)?', s) if len(x) >= 2 and x not in ('10', '20', '100')}


def _latin_of(u):
    s = ' '.join(str(u.get(k, '')) if not isinstance(u.get(k), list) else ' '.join(map(str, u[k]))
                 for k in ('name', 'abbr', 'sample', 'materials', 'component', 'product'))
    return {t.lower() for t in re.findall(r'[A-Za-z][A-Za-z0-9\-]{2,}', s)}


def _cos(a, b):
    d = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return d / (na * nb) if na and nb else 0.0


def match_paper(ref_units, src_units, embed):
    """范文单元逐条配原文单元 → 每条 {'type', 'how': 'num|name|panel|sim|none', 'sim': 最高相似度}。"""
    src_nums = set()
    for s in src_units:
        src_nums |= _nums_of(s)
    src_latin = set()
    for s in src_units:
        if s['type'] == 'entity':
            src_latin |= _latin_of(s)
    src_panels = {(str(s.get('figure', '')).strip(), str(s.get('subpanel', '')).strip().lower()) for s in src_units if s['type'] == 'panel'}
    by_type = {}
    for s in src_units:
        by_type.setdefault(s['type'], []).append(s)
    vec_cache = {}                                   # 按类缓存原文单元的向量：每类只向量化一次

    def vecs_by_type(t):
        if t not in vec_cache:
            us = by_type.get(t, [])
            vec_cache[t] = embed([text_of(u) for u in us]) if us else []
        return vec_cache[t]

    out = []
    sem = []
    for r in ref_units:
        t = refine_ref(r)
        rec = {'type': t, 'how': 'none', 'sim': None}
        if t == 'fact':
            if _nums_of(r) & src_nums:
                rec['how'] = 'num'
        elif t == 'entity':
            if _latin_of(r) & src_latin:
                rec['how'] = 'name'
        elif t == 'panel':
            fig, sub = str(r.get('figure', '')).strip(), str(r.get('subpanel', '')).strip().lower()
            if (fig, sub) in src_panels or (fig, '') in src_panels or any(f == fig for f, _ in src_panels):
                rec['how'] = 'panel'
        else:
            sem.append((r, t, rec))
        out.append(rec)
    # 语义配对：按类分组批量算向量
    if sem:
        rv = embed([text_of(r) for r, _, _ in sem])
        for (r, t, rec), v in zip(sem, rv):
            cvs = []
            for nt in NEAR.get(t, (t,)):
                cvs += vecs_by_type(nt)
            if not cvs:
                continue
            best = max((_cos(v, cv) for cv in cvs), default=0.0)
            rec['sim'] = round(best, 3)
            if best >= SIM_LINE:
                rec['how'] = 'sim'
    return out


def _batched(embed, size=48, max_chars=1200):
    """分批 embed 已下沉到 shared.adapters.embed.embed_batched（review 也用）；这里留个同形状的壳。"""
    from shared.adapters.embed import embed_batched
    return lambda texts: embed_batched(texts, size=size, max_chars=max_chars)


def coverage(tag, embed=None, log=print):
    from shared.adapters.embed import embed as _embed
    embed = _batched(embed or _embed)
    out_dir = paths.unit_study_dir(tag)
    per_type = {t: {'n': 0, 'covered': 0, 'sims': []} for t in TYPES}
    rows = []
    for f in sorted(os.listdir(out_dir)):
        if not f.endswith('.src.json'):
            continue
        pid = f[:-len('.src.json')]
        rf = os.path.join(out_dir, pid + '.json')
        if not os.path.exists(rf):
            continue
        ref = json.load(io.open(rf, encoding='utf-8'))['units']
        src = json.load(io.open(os.path.join(out_dir, f), encoding='utf-8'))['units']
        m = match_paper(ref, src, embed)
        cnt = {t: [0, 0] for t in TYPES}
        for rec in m:
            cnt[rec['type']][0] += 1
            cnt[rec['type']][1] += rec['how'] != 'none'
            per_type[rec['type']]['n'] += 1
            per_type[rec['type']]['covered'] += rec['how'] != 'none'
            if rec['sim'] is not None:
                per_type[rec['type']]['sims'].append(rec['sim'])
        src_cnt = {}
        for s in src:
            src_cnt[s['type']] = src_cnt.get(s['type'], 0) + 1
        rows.append({'pid': pid, 'ref': len(ref), 'src': len(src), 'src_by_type': src_cnt,
                     'cover': {t: '%d/%d' % (c[1], c[0]) for t, c in cnt.items() if c[0]}})
        log('%s 范文 %d 条 · 原文 %d 条 · 覆盖 %s' % (pid, len(ref), len(src), rows[-1]['cover']))
    for t, b in per_type.items():
        b['rate'] = round(b['covered'] / b['n'], 3) if b['n'] else None
        ss = sorted(b['sims'])
        b['sim_quartiles'] = [ss[len(ss) * q // 4] for q in (1, 2, 3)] if len(ss) >= 4 else ss
        del b['sims']
    when = time.strftime('%Y-%m-%d %H:%M')
    json.dump({'tag': tag, 'when': when, 'sim_line': SIM_LINE, 'per_type': per_type, 'rows': rows},
              io.open(os.path.join(out_dir, 'coverage.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    L = ['# 单元覆盖 %s（%s）' % (tag, when), '',
         '范文单元里，能在**只看原文拆出的单元**中找到对应的比例。数值类按数配，实体按缩写/名字，图面板按图号，其余按 bge-m3 相似度 ≥ %.2f。' % SIM_LINE, '',
         '| 类 | 范文条数 | 覆盖 | 覆盖率 | 语义相似度四分位（仅语义类） |', '|---|---|---|---|---|']
    for t in TYPES:
        b = per_type[t]
        if b['n']:
            L.append('| %s | %d | %d | %s | %s |' % (t, b['n'], b['covered'], b['rate'], ' / '.join(str(x) for x in b['sim_quartiles']) or '—'))
    L += ['', '| 篇 | 范文单元 | 原文单元 | 各类覆盖 |', '|---|---|---|---|']
    for r in rows:
        L.append('| %s | %d | %d | %s |' % (r['pid'], r['ref'], r['src'], ', '.join('%s %s' % kv for kv in r['cover'].items())))
    io.open(os.path.join(out_dir, 'coverage.md'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    return per_type, os.path.join(out_dir, 'coverage.md')


# ── 第 3 步：召回 + 小模型判同异（2026-09-21）────────────────────────
# 相似度阈值法在语义类上不可信（每类错配方向都不一样，见规划第八节）。Pyramid 的正规做法是：
# 相似度只负责召回前几名，「是不是同一件事」交给一个判断模型。这也是小模型（4b）的第一次实测场。

MATCH_PROMPT = 'units_match@v1'
SEM_TYPES = ('attribute', 'action', 'method', 'claim', 'role', 'cause', 'entity')
TOPK = 3


def _top_candidates(t, v, by_type, vecs_by_type, k=TOPK):
    """按相似度从近类里取前 k 条候选。entity 只在 entity 里找。"""
    scored = []
    for nt in (NEAR.get(t, (t,)) if t != 'entity' else ('entity',)):
        for u, cv in zip(by_type.get(nt, []), vecs_by_type(nt)):
            scored.append((_cos(v, cv), u))
    scored.sort(key=lambda x: -x[0])
    return scored[:k]


def judge_one(chat_json, ref, cands, model, log=print):
    """→ (match_index 0..k, 失败与否)。一次调用判一条范文单元。"""
    sysp = prompts.load('deepread', MATCH_PROMPT)
    user = 'A（精读单元，类型 %s）：%s\n\n候选：\n%s' % (
        refine_ref(ref), text_of(ref), '\n'.join('%d. %s' % (i + 1, text_of(u)) for i, (_, u) in enumerate(cands)))
    try:
        d = chat_json(sysp, user, provider='ollama', model=model, temperature=0.0, num_ctx=4096) or {}
        m = int(d.get('match', 0))
        return (m if 0 <= m <= len(cands) else 0), False
    except Exception as e:
        log('  判同异失败：%s' % str(e)[:80])
        return 0, True


def _collect_items(tag, embed):
    """所有语义类范文单元 + 各自的 top-k 候选（向量按篇按类只算一次）。"""
    out_dir = paths.unit_study_dir(tag)
    items = []
    for f in sorted(os.listdir(out_dir)):
        if not f.endswith('.src.json'):
            continue
        pid = f[:-len('.src.json')]
        rf = os.path.join(out_dir, pid + '.json')
        if not os.path.exists(rf):
            continue
        ref = json.load(io.open(rf, encoding='utf-8'))['units']
        src = json.load(io.open(os.path.join(out_dir, f), encoding='utf-8'))['units']
        by_type = {}
        for s in src:
            by_type.setdefault(s['type'], []).append(s)
        cache = {}

        def vecs_by_type(t, _c=cache, _b=by_type):
            if t not in _c:
                us = _b.get(t, [])
                _c[t] = embed([text_of(u) for u in us]) if us else []
            return _c[t]
        sem = [(i, r, refine_ref(r)) for i, r in enumerate(ref) if refine_ref(r) in SEM_TYPES]
        if not sem:
            continue
        rv = embed([text_of(r) for _, r, _ in sem])
        for (i, r, t), v in zip(sem, rv):
            items.append({'pid': pid, 'i': i, 'type': t, 'ref': r, 'cands': _top_candidates(t, v, by_type, vecs_by_type)})
    return items


def judge_coverage(tag, chat_json, model, embed=None, limit=None, sample_seed=1, log=print):
    """语义类范文单元：召回 top-3 → 模型判同异 → 覆盖。结果落 judged_<model>[_nN].json + coverage_judged_<model>[_nN].md。

    `limit`：只判随机抽出的 N 条（同一个 seed 抽同一批，给两个模型做对照用）。
    """
    import random
    from shared.adapters.embed import embed as _embed
    embed = _batched(embed or _embed)
    out_dir = paths.unit_study_dir(tag)
    items = _collect_items(tag, embed)
    if limit:
        rng = random.Random(sample_seed)
        rng.shuffle(items)
        items = sorted(items[:limit], key=lambda x: (x['pid'], x['i']))
    per_type = {t: {'n': 0, 'covered': 0, 'yes_sims': []} for t in SEM_TYPES}
    results = []
    for n, it in enumerate(items, 1):
        m, bad = judge_one(chat_json, it['ref'], it['cands'], model, log) if it['cands'] else (0, False)
        rec = {'pid': it['pid'], 'i': it['i'], 'type': it['type'], 'match': m, 'failed': bad,
               'top_sims': [round(s, 3) for s, _ in it['cands']],
               'ref': text_of(it['ref'])[:200], 'picked': text_of(it['cands'][m - 1][1])[:200] if m else ''}
        results.append(rec)
        b = per_type[it['type']]
        b['n'] += 1
        b['covered'] += bool(m)
        if m:
            b['yes_sims'].append(rec['top_sims'][0])
        if n % 25 == 0:
            log('  判了 %d/%d' % (n, len(items)))
    for t, b in per_type.items():
        b['rate'] = round(b['covered'] / b['n'], 3) if b['n'] else None
        ss = sorted(b['yes_sims'])
        b['sim_when_yes_median'] = ss[len(ss) // 2] if ss else None
        del b['yes_sims']
    when = time.strftime('%Y-%m-%d %H:%M')
    suffix = re.sub(r'[^A-Za-z0-9._-]+', '-', model) + ('_n%d' % limit if limit else '')
    json.dump({'tag': tag, 'model': model, 'when': when, 'limit': limit, 'per_type': per_type, 'items': results},
              io.open(os.path.join(out_dir, 'judged_%s.json' % suffix), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    L = ['# 单元覆盖（召回 top-%d + %s 判同异）%s（%s）' % (TOPK, model, tag, when), '',
         '| 类 | 条数 | 判为同一件事 | 覆盖率 | 判「是」时 top-1 相似度中位 |', '|---|---|---|---|---|']
    for t in SEM_TYPES:
        b = per_type[t]
        if b['n']:
            L.append('| %s | %d | %d | %s | %s |' % (t, b['n'], b['covered'], b['rate'], b['sim_when_yes_median']))
    io.open(os.path.join(out_dir, 'coverage_judged_%s.md' % suffix), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    return per_type, results


def compare_judges(tag, model_a, model_b, limit):
    """两个模型在同一批抽样上的判断一致率（`judge_coverage` 用同一个 seed 抽的那批）。"""
    out_dir = paths.unit_study_dir(tag)

    def load(m):
        p = os.path.join(out_dir, 'judged_%s_n%d.json' % (re.sub(r'[^A-Za-z0-9._-]+', '-', m), limit))
        return {(x['pid'], x['i']): x for x in json.load(io.open(p, encoding='utf-8'))['items']}
    a, b = load(model_a), load(model_b)
    keys = sorted(set(a) & set(b))
    agree = sum(1 for k in keys if bool(a[k]['match']) == bool(b[k]['match']))
    same_pick = sum(1 for k in keys if a[k]['match'] == b[k]['match'])
    diff = [(k, a[k], b[k]) for k in keys if bool(a[k]['match']) != bool(b[k]['match'])]
    L = ['# 判同异对照 %s vs %s（%d 条）' % (model_a, model_b, len(keys)), '',
         '是/否一致 %d/%d（%.0f%%）；选中同一条 %d/%d' % (agree, len(keys), 100 * agree / max(1, len(keys)), same_pick, len(keys)),
         '', '## 不一致的（前 30 条）', '']
    for k, x, y in diff[:30]:
        L.append('- [%s] %s\n  %s 选 %s：%s\n  %s 选 %s：%s' % (
            x['type'], x['ref'][:100], model_a, x['match'], x['picked'][:90], model_b, y['match'], y['picked'][:90]))
    p = os.path.join(out_dir, 'judge_compare.md')
    io.open(p, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    return agree, len(keys), p
