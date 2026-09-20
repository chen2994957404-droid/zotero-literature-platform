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
    vec_cache = {}

    def vecs(units):
        key = id(units)
        if key not in vec_cache:
            vec_cache[key] = embed([text_of(u) for u in units]) if units else []
        return vec_cache[key]

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
            cands = []
            for nt in NEAR.get(t, (t,)):
                cands += by_type.get(nt, [])
            if not cands:
                continue
            best = max((_cos(v, cv) for cv in vecs(cands)), default=0.0)
            rec['sim'] = round(best, 3)
            if best >= SIM_LINE:
                rec['how'] = 'sim'
    return out


def coverage(tag, embed=None, log=print):
    from shared.adapters.embed import embed as _embed
    embed = embed or _embed
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
