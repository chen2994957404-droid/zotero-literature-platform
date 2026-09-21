# -*- coding: utf-8 -*-
"""fine_fact · 数值事实的**字段级拆分抽取**（2026-09-21，本地化拆解的抽取试验）。

**为什么**：一次调用让模型「找句子 → 判类型 → 填全部字段」，小模型扛不住（单元拆解第 2/3 步实测）。
拆成字段级的封闭题，每一步要么脚本做、要么是选择题，1–4B 才有用武之地：

    ① 脚本   `scan.scan_numbers` 找出每个「数 + 单位」和它的上下文（T0）
    ② 脚本   样品名单：表格行首 + 样品编号正则（T0）
    ③ 模型   「这个数是哪个样品的？」—— 从名单里选序号，0 = 没说（T1）
    ④ 模型   「是哪项性质？」—— 从性质词表里选序号，0 = 不是性质（投料量 / 条件 / 引用号）（T1）
    ⑤ 脚本   核对：选中的样品名必须出现在上下文窗口里，否则退回「没说」（T0）

标尺：单元研究里范文的数值事实（`data/state/unit_study/<tag>/<pid>.json` 里 type=fact 且带数字）——
覆盖率按数值 norm 相等算，跟第 2 步 9.7B 一次拆的 65% 直接可比。

用法：python -m tools.extract.fine_fact --tag u1 --model gemma3:1b        单模型跑同批
      python -m tools.extract.fine_fact --tag u1 --model qwen3.5:4b --分区 qwen3.5:4b   先句子分区再问（第 0 步）
      python -m tools.extract.fine_fact --tag u1 --models gemma3:1b,qwen3.5:2b,qwen3.5:4b   多模型对照
产物：data/state/unit_study/<tag>/fine_fact_<model>.json + fine_fact_report.md。只读，不写别处。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

import io
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from shared.domain import numcheck as _nums
from shared.domain.schema import PROPERTY_ALIASES, _ALIAS_TO_CANON, normalize_property_name
from shared.domain.schema import scan
from shared.kernel import paths
from shared.kernel.cli import flag, opt, wants_help
from tools.extract import zoning

PROPS = list(PROPERTY_ALIASES.keys())
_CODE = re.compile(r'\b[A-Z]{2,}[A-Za-z0-9]*(?:-[A-Za-z0-9]+){1,3}\b')
_DIGIT = re.compile(r'\d')
NUM_CTX = 2048
WINDOW = 220            # 给模型看的上下文：数前后各这么多字符
# T0 预筛（2026-09-21）：这些单位的数几乎总是投料量 / 时间 / 体积，不是性能 —— 直接判「条件」，不问模型。
# 温度（°C）不在这里：Tg / Td 是性质，反应温度是条件，得看句子。
_COND_UNITS = {'h', 'hr', 'min', 's', 'ml', 'l', 'g', 'mg', 'kg', 'mol', 'mmol', 'μl', 'ul', 'rpm', 'day', 'days', 'week', 'weeks',
               'cm-1', 'cm^-1', 'ppm', 'nm', 'ev', 'mhz', 'khz'}   # 波数 / 化学位移 / 波长 / 能量 / 频率：仪器读数，不是性能
# 分区后只有这几种句子里的数才可能是性质
_FACT_ZONES = {'RESULT', 'FIGURE', 'CLAIM'}
# 含糊单位：在方法/背景句里出现时当条件处理（软过滤只对这些生效）
_AMBIG_UNITS = {'°c', '℃', 'k', '%', 'wt%', 'wt.%', 'vol%', 'mol%', 'mm', 'cm', 'm', 'µm', 'um', 'nm', 'rpm', 'v', 'hz', 'ms', 'times', '-fold', 'fold', '×', ''}

SYS_SAMPLE = ('You answer with ONE integer only. A sentence from a materials paper is given, with one number '
              'highlighted like <<12.5 MPa>>. Which sample does that number belong to? Choose the option index. '
              'Answer 0 if the sentence does not say or the number is not about any listed sample.')
SYS_PROP = ('You answer with ONE integer only. A sentence from a materials paper is given, with one number '
            'highlighted like <<12.5 MPa>>. Which material property does that number measure? Choose the option index. '
            'Answer 0 if it is not a measured property (an ingredient amount, a processing condition such as temperature '
            'or time, a reference number, a page number, a wavelength, or an instrument setting).')


def sample_list(md, limit=30):
    """样品名单（T0）：表格行首 + 出现 ≥2 次的样品编号。"""
    names = []
    for t in scan.scan_tables(md):
        s = (t.get('sample_id') or '').strip()
        if s and s not in names and len(s) <= 40:
            names.append(s)
    counts = {}
    for m in _CODE.finditer(md):
        counts[m.group(0)] = counts.get(m.group(0), 0) + 1
    for m in re.finditer(r'\b[A-Z]{2,6}\d{0,3}\b', md):             # 光杆缩写（PBS、PDMS、CAN30）出现 ≥3 次也算
        counts[m.group(0)] = counts.get(m.group(0), 0) + 1
    for c, n in sorted(counts.items(), key=lambda x: -x[1]):
        need = 2 if '-' in c else 3
        if n >= need and c not in names and not c.lower().startswith(('fig', 'tab', 'doi', 'http', 'si', 'iii')):
            names.append(c)
    return names[:limit]


def _ask_int(chat, sysp, user, model, n_opts, options=()):
    """→ 选项序号或 None。小模型常不听「只答数字」而答选项原文（1B 实测），所以按文本也认。"""
    try:
        raw = chat(sysp, user + '\n\nReply with the option number only.', provider='ollama', model=model,
                   temperature=0.0, max_tokens=12, num_ctx=NUM_CTX, thinking=False)
    except Exception:
        return None
    raw = (raw or '').strip()
    m = re.match(r'\s*\(?(\d+)[.)\s]?', raw)
    if m and 0 <= int(m.group(1)) <= n_opts:
        return int(m.group(1))
    low = raw.lower()
    for i, o in enumerate(options, 1):
        if o.lower() == low or low.startswith(o.lower()):
            return i
    if low.startswith(('none', 'not', 'unknown', 'no ')):
        return 0
    return None


def _highlight(md, c):
    start = md.find(c['raw'], c['pos'], c['pos'] + len(c['raw']) + 4)     # scan 的 pos 可能带着前导空格
    if start < 0:
        start = c['pos']
    end = start + len(c['raw'])
    a, b = max(0, start - WINDOW), min(len(md), end + WINDOW)
    return (md[a:start] + '<<' + c['raw'] + '>>' + md[end:b]).replace('\n', ' ')


def _drop_nonbody(md):
    """按骨架把参考文献 / 致谢 / 作者信息这些非正文区挖掉（保留位置不重要，候选只要文本）。"""
    from shared.domain.schema import outline as _ol
    o = _ol.build_outline(md)
    spans = sorted((s['start'], s['end']) for s in o.get('sections') or [] if s['kind'] == _ol.NONBODY)
    if not spans:
        return md
    out, pos = [], 0
    for a, b in spans:
        out.append(md[pos:a])
        pos = max(pos, b)
    out.append(md[pos:])
    return ''.join(out)


GROUP = 6               # 一次调用最多问几个数
PARALLEL = 4            # 同时发几路请求（Ollama 侧要开 OLLAMA_NUM_PARALLEL 才真并行）


_OTHER = 'other measured property (not in this list)'


def props_in_window(text):
    """窗口文本里提到了词表中的哪些性质（按别名匹配，长别名优先）。→ [正名]，按出现位置排。"""
    low = text.lower()
    found = {}
    for alias, canon in _ALIAS_TO_CANON:
        if canon in found or len(alias) < 3:
            continue
        m = re.search(r'(^|[^a-z])' + re.escape(alias) + r'($|[^a-z])', low)
        if m:
            found[canon] = m.start()
    return [c for c, _ in sorted(found.items(), key=lambda kv: kv[1])]


def _options_for(win):
    """一组候选的选项表：窗口里提到的性质（通常 1–5 个）+ 「其他性质」；提不到就退回全表。"""
    opts = props_in_window(win)
    return (opts + [_OTHER]) if opts else (PROPS + [_OTHER])


def _group(todo):
    """相邻候选攒组：同一来源文本、位置相近（窗口能装下）的最多 GROUP 个一组。"""
    groups, cur = [], []
    for item in todo:
        if cur and (len(cur) >= GROUP or item[0] is not cur[-1][0] or item[1]['pos'] - cur[0][1]['pos'] > 2 * WINDOW):
            groups.append(cur)
            cur = []
        cur.append(item)
    if cur:
        groups.append(cur)
    return groups


def _window(group):
    """一组候选共用的窗口文本，每个数按 <<k: 12.5 MPa>> 标号高亮。"""
    src_text = group[0][0]
    starts = []
    for _, c in group:
        st = src_text.find(c['raw'], c['pos'], c['pos'] + len(c['raw']) + 4)
        starts.append(st if st >= 0 else c['pos'])
    a = max(0, starts[0] - WINDOW)
    b = min(len(src_text), starts[-1] + len(group[-1][1]['raw']) + WINDOW)
    out, pos = [], a
    for k, ((_, c), st) in enumerate(zip(group, starts), 1):
        if st < pos:
            continue
        out.append(src_text[pos:st])
        out.append('<<%d: %s>>' % (k, c['raw']))
        pos = st + len(c['raw'])
    out.append(src_text[pos:b])
    return ''.join(out).replace('\n', ' ')


def _ask_list(chat, sysp, user, model, n_items, n_opts):
    """一次答 n_items 个序号（每行 `k: 序号`）。答不齐 → None，调用方退回逐个问。"""
    try:
        raw = chat(sysp, user + '\n\nReply with one line per number, in the form `k: option`, nothing else.',
                   provider='ollama', model=model, temperature=0.0, max_tokens=6 * n_items + 4, num_ctx=NUM_CTX, thinking=False)
    except Exception:
        return None
    got = {}
    for k, v in re.findall(r'(\d+)\s*[:：.)-]\s*(\d+)', raw or ''):
        k, v = int(k), int(v)
        if 1 <= k <= n_items and 0 <= v <= n_opts:
            got[k] = v
    if len(got) != n_items:
        return None
    return [got[k] for k in range(1, n_items + 1)]


def _ask_names(chat, user, model, n_items, opts):
    """性质题：每行 `k: <性质名或 0>`。名字优先对到 opts（序号或原文都认），对不上就归一后照收。答不齐 → None。"""
    try:
        raw = chat(SYS_PROP_MULTI, user + '\n\nReply with one line per number: `k: property name` (copy a listed name if it fits, '
                   'otherwise write the property in 2-4 words), or `k: 0` if it is not a measured material property. Nothing else.',
                   provider='ollama', model=model, temperature=0.0, max_tokens=14 * n_items + 6, num_ctx=NUM_CTX, thinking=False)
    except Exception:
        return None
    got = {}
    for line in (raw or '').splitlines():
        m = re.match(r'\s*(\d+)\s*[:：.)-]\s*(.+?)\s*$', line)
        if not m:
            continue
        k, v = int(m.group(1)), m.group(2).strip().strip('`"\'')
        if not 1 <= k <= n_items:
            continue
        if v in ('0', 'none', 'None', 'no', 'not a property'):
            got[k] = 0
        elif v.isdigit() and 1 <= int(v) <= len(opts):
            got[k] = opts[int(v) - 1]
        else:
            canon = normalize_property_name(v)
            got[k] = canon if canon else 0
    if len(got) != n_items:
        return None
    return [got[k] for k in range(1, n_items + 1)]


def _answer_group(group, chat, model, samples, stats):
    """一组候选 → ([性质序号或 None], [样品序号])。"""
    n = len(group)
    win = _window(group)
    opts = props_in_window(win)                           # 窗口里提到的性质名（通常 1–5 个）作提示；模型也可以自己写名字
    opts_txt = '\n'.join('%d. %s' % (i + 1, p) for i, p in enumerate(opts)) if opts else '(none mentioned nearby)'
    user = 'Passage (numbers marked <<k: value>>): %s\n\nProperty names mentioned nearby:\n%s' % (win, opts_txt)
    stats['asked'] += 1
    props = _ask_names(chat, user, model, n, opts)
    if props is None:                                      # 退回逐个问（同一题型，一次一个数）
        props = []
        for src_text, c in group:
            u = 'Passage (numbers marked <<k: value>>): %s\n\nProperty names mentioned nearby:\n%s' % (
                _highlight(src_text, c).replace('<<', '<<1: '), opts_txt)
            stats['asked'] += 1
            r = _ask_names(chat, u, model, 1, opts)
            props.append(r[0] if r else None)
    sids = [0] * n
    need = [k for k, p in enumerate(props) if p]
    if samples and need:
        s_txt = '\n'.join('%d. %s' % (i + 1, x) for i, x in enumerate(samples))
        user = 'Passage (numbers marked <<k: value>>): %s\n\nOptions (samples):\n%s' % (win, s_txt)
        stats['asked'] += 1
        ans = _ask_list(chat, SYS_SAMPLE_MULTI, user, model, n, len(samples))
        if ans is None:
            ans = [0] * n
            for k in need:
                src_text, c = group[k]
                u = 'Sentence: %s\n\nOptions (samples):\n%s' % (_highlight(src_text, c), s_txt)
                stats['asked'] += 1
                ans[k] = _ask_int(chat, SYS_SAMPLE, u, model, len(samples), samples) or 0
        sids = ans
    return props, sids


SYS_PROP_MULTI = ('A passage from a materials paper is given. Several numbers are marked like <<1: 12.5 MPa>>, <<2: 850%>>. '
                  'For EACH marked number, name the MATERIAL PROPERTY it measures (tensile strength, toughness, glass transition '
                  'temperature, crystallinity, ...). Answer 0 if it is NOT a measured property of a material: an ingredient amount, '
                  'a sample dimension, a processing temperature / time / speed, a reference or page number, a wavenumber, wavelength, '
                  'diffraction angle or other instrument reading. A ratio like "5.1 times the strength of X" IS a property (name the property).')
SYS_SAMPLE_MULTI = ('A passage from a materials paper is given. Several numbers are marked like <<1: 12.5 MPa>>. '
                    'For EACH marked number, decide which listed sample it belongs to and answer the option index; '
                    'answer 0 if the passage does not say. Answer one line per number: `k: option`.')


def _local_sentence(text, c):
    """候选数所在的那句话（在 clean 文本里按句末标点往两边找）。"""
    start = text.find(c['raw'], c['pos'], c['pos'] + len(c['raw']) + 4)
    if start < 0:
        start = c['pos']
    a = max(text.rfind('. ', 0, start), text.rfind('\n', 0, start), -1) + 1
    b_dot, b_nl = text.find('. ', start), text.find('\n', start)
    b = min(x for x in (b_dot + 1 if b_dot >= 0 else len(text), b_nl if b_nl >= 0 else len(text)))
    return ' '.join(text[a:b].split())


def _zone_candidates(cands, chat, zone_model, stats):
    """候选所在句子分区（去重后一次 8 句）→ {句: 区}。"""
    sents = []
    for src_text, c in cands:
        sent = _local_sentence(src_text, c)
        if sent and sent not in sents:
            sents.append(sent)
    zones = {}
    for i in range(0, len(sents), zoning.BATCH):
        batch = sents[i:i + zoning.BATCH]
        zs = zoning._ask(chat, zone_model, batch)
        stats['zone_calls'] += 1
        if zs is None:
            for x in batch:
                z = zoning._ask(chat, zone_model, [x])
                stats['zone_calls'] += 1
                zones[x] = z[0] if z else 'RESULT'
        else:
            zones.update(zip(batch, zs))
    return zones


def extract_paper(md, chat, model, log=print, si_md='', zone_model=None):
    """一篇 → 数值事实列表 + 统计。每个候选：T0 预筛 → （可选）句子分区 → 两次封闭题。

    `zone_model` 给了就先分区：只对 RESULT / FIGURE / CLAIM 句里的数问「哪项性质」，
    METHOD / BACKGROUND / OTHER 句里的数记成条件、不问。
    """
    # 正文 + SI 一起扫（2026-09-21 中途实测：只扫正文时范文数命中 45%，9.7B 把 SI 切进去的一次拆 77% —— 差在找数的范围）
    text = scan.clean_body(_drop_nonbody(md)) if md else ''       # 参考文献区不进候选：页码、年份全是数
    si_text = scan.clean_body(_drop_nonbody(si_md)) if si_md else ''
    samples = sample_list(md + '\n' + (si_md or ''))
    facts, dropped, stats = [], [], {'cands': 0, 'asked': 0, 'no_answer': 0, 'not_prop': 0, 'sample_unspec': 0, 'sample_bad': 0,
                        'cond_unit': 0, 'zoned_out': 0, 'zone_calls': 0, 'secs': 0.0}
    t0 = time.time()
    cands = [(text, c) for c in scan.scan_numbers(text)] + [(si_text, c) for c in scan.scan_numbers(si_text)]
    cands = [(t, c) for t, c in cands if c['value'] is not None and not c.get('in_table')]   # 表格由 scan_tables 全脚本处理
    stats['cands'] = len(cands)
    # T0 预筛：投料 / 时间 / 体积单位的数不是性质
    kept = []
    for t, c in cands:
        if (c.get('unit') or '').strip().lower().replace(' ', '') in _COND_UNITS:
            stats['cond_unit'] += 1
            dropped.append({'norm': _nums.norm(str(c['value'])), 'why': 'cond_unit', 'raw': c['raw'], 'ctx': c['context'][:120]})
        else:
            kept.append((t, c))
    cands = kept
    zones = _zone_candidates(cands, chat, zone_model, stats) if zone_model else {}
    # 分区筛
    todo = []
    for src_text, c in cands:
        # 分区是软过滤（2026-09-21 实测：4B 把「glass transition occurred at 90°C」判成方法句）：
        # 只有「句子是方法/背景」且「单位本身含糊」（温度、百分比、时间这类既可能是条件也可能是性质）才跳过；
        # MPa / GPa / kJ/mol 这种一看就是性能的单位，不管在哪种句子里都问。
        unit_l = (c.get('unit') or '').strip().lower().replace(' ', '')
        if zones and zones.get(_local_sentence(src_text, c), 'RESULT') not in _FACT_ZONES and unit_l in _AMBIG_UNITS:
            stats['zoned_out'] += 1
            dropped.append({'norm': _nums.norm(str(c['value'])), 'why': 'zone:' + zones.get(_local_sentence(src_text, c), '?'),
                            'raw': c['raw'], 'ctx': c['context'][:120]})
            continue
        todo.append((src_text, c))
    # 一次调用多道题（2026-09-21 实测：一次 1B 调用 2.07 s，模型只干 0.04 s，其余是固定开销 —— 请求数才是成本）：
    # 相邻的候选攒成一组（同一片窗口里最多 GROUP 个数），一次问「每个数各是哪项性质」，再一次问「各是哪个样品」。
    groups = _group(todo)
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        results = list(pool.map(lambda g: _answer_group(g, chat, model, samples, stats), groups))
    for g, (props, sids) in zip(groups, results):
        for (src_text, c), pi, si in zip(g, props, sids):
            if pi is None:
                stats['no_answer'] += 1
                dropped.append({'norm': _nums.norm(str(c['value'])), 'why': 'no_answer', 'raw': c['raw'], 'ctx': c['context'][:120]})
                continue
            if pi == 0:
                stats['not_prop'] += 1
                dropped.append({'norm': _nums.norm(str(c['value'])), 'why': 'not_prop', 'raw': c['raw'], 'ctx': c['context'][:120]})
                continue
            if pi not in PROPERTY_ALIASES:
                stats['free_name'] = stats.get('free_name', 0) + 1     # 模型自己起的名（词表外），照收，供词表下一轮扩
            sent = _highlight(src_text, c)
            sample = samples[si - 1] if si else ''
            if sample and sample.lower() not in sent.lower():    # ⑤ 核对：样品名要在窗口里
                stats['sample_bad'] += 1
                sample = ''
            if not sample:
                stats['sample_unspec'] += 1
            facts.append({'sample': sample, 'property': pi, 'value': c['raw'], 'unit': c['unit'],
                          'norm': _nums.norm(str(c['value'])), 'location': c.get('location', ''), 'ctx': c['context'][:160]})
    stats['secs'] = round(time.time() - t0, 1)
    stats['dropped'] = dropped
    return facts, stats


def ref_numbers(pid, tag):
    """范文数值事实的数（norm）—— 标尺。"""
    p = os.path.join(paths.unit_study_dir(tag), pid + '.json')
    out = set()
    for u in json.load(io.open(p, encoding='utf-8'))['units']:
        if u['type'] == 'fact' and _DIGIT.search(str(u.get('value', '')) + str(u.get('unit', ''))):
            for x in re.findall(r'\d+(?:\.\d+)?', str(u.get('value', ''))):
                if len(x) >= 2 and x not in ('10', '20', '100'):
                    out.add(_nums.norm(x))
    return out


def src_numbers(pid, tag):
    """第 2 步 9.7B 一次拆出的数值事实（对照）。"""
    p = os.path.join(paths.unit_study_dir(tag), pid + '.src.json')
    out = set()
    if not os.path.exists(p):
        return out
    for u in json.load(io.open(p, encoding='utf-8'))['units']:
        if u['type'] == 'fact':
            for x in re.findall(r'\d+(?:\.\d+)?', str(u.get('value', ''))):
                if len(x) >= 2 and x not in ('10', '20', '100'):
                    out.add(_nums.norm(x))
    return out


def run(tag, models, keys=None, log=print, zone_model=None):
    from shared.adapters.llm_client import chat
    d = paths.unit_study_dir(tag)
    pids = keys or sorted(f[:-9] for f in os.listdir(d) if f.endswith('.src.json'))
    report = {}
    for model in models:
        zm = model if zone_model == 'same' else zone_model      # --分区 same：各模型自己分区
        rows = []
        for pid in pids:
            md = io.open(paths.fulltext(pid), encoding='utf-8').read()
            sp = paths.si_fulltext(pid)
            si = io.open(sp, encoding='utf-8').read() if os.path.exists(sp) else ''
            log('[%s] %s' % (model, pid))
            facts, st = extract_paper(md, chat, model, log, si_md=si, zone_model=zm)
            got = {f['norm'] for f in facts}
            ref, one = ref_numbers(pid, tag), src_numbers(pid, tag)
            lost = {}
            for dr in st.pop('dropped', []):
                if dr['norm'] in ref and dr['norm'] not in got:
                    lost.setdefault(dr['why'].split(':')[0], []).append(dr)
            st['lost_ref'] = {k: len(v) for k, v in lost.items()}
            st['lost_samples'] = [dict(x, why=k) for k, v in lost.items() for x in v[:3]]
            table_nums = {_nums.norm(str(t['value'])) for t in scan.scan_tables(md) if t.get('value') is not None}
            rows.append({'pid': pid, 'n_facts': len(facts), 'with_sample': sum(1 for f in facts if f['sample']),
                         'ref': len(ref), 'ref_hit': len(ref & (got | table_nums)), 'ref_hit_model_only': len(ref & got),
                         'one_shot_hit': len(ref & one), **st})
            log('   候选 %d（单位筛掉 %d、分区筛掉 %d、分区调用 %d）→ 事实 %d（带样品 %d）· 范文数 %d：拆分法命中 %d（含表 %d）· 一次拆命中 %d · %ss · 范文数丢在 %s' % (
                st['cands'], st['cond_unit'], st['zoned_out'], st['zone_calls'], len(facts), rows[-1]['with_sample'], len(ref),
                rows[-1]['ref_hit_model_only'], rows[-1]['ref_hit'], rows[-1]['one_shot_hit'], st['secs'], st['lost_ref']))
            json.dump({'model': model, 'pid': pid, 'facts': facts, 'stats': st},
                      io.open(os.path.join(d, 'fine_fact_%s_%s.json' % (re.sub(r'[^A-Za-z0-9.-]+', '-', model), pid)), 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=1)
        report[model] = rows
    _write(d, report)
    return report


def _write(d, report):
    L = ['# 数值事实 · 字段级拆分抽取（%s）' % time.strftime('%Y-%m-%d %H:%M'), '',
         '标尺 = 范文里带数字的事实（按数值配）。「一次拆」= 第 2 步 9.7B 整段一次抽的 fact。', '',
         '| 模型 | 篇 | 候选数 | 单位筛掉 | 分区筛掉 | 判非性质 | 抽出事实 | 带样品 | 范文数 | 拆分法命中(含表) | 仅模型 | 一次拆命中 | 秒/篇 |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for model, rows in report.items():
        tot = lambda k: sum(r[k] for r in rows)
        L.append('| %s | %d | %d | %d | %d | %d | %d | %d | %d | **%d (%.0f%%)** | %d (%.0f%%) | %d (%.0f%%) | %.0f |' % (
            model, len(rows), tot('cands'), tot('cond_unit'), tot('zoned_out'), tot('not_prop'), tot('n_facts'), tot('with_sample'), tot('ref'),
            tot('ref_hit'), 100 * tot('ref_hit') / max(1, tot('ref')),
            tot('ref_hit_model_only'), 100 * tot('ref_hit_model_only') / max(1, tot('ref')),
            tot('one_shot_hit'), 100 * tot('one_shot_hit') / max(1, tot('ref')),
            tot('secs') / max(1, len(rows))))
    L += ['', '逐篇：', '']
    for model, rows in report.items():
        L.append('## %s' % model)
        L.append('| 篇 | 候选 | 事实 | 带样品 | 范文数 | 命中(含表) | 仅模型 | 一次拆 | 秒 |')
        L.append('|---|---|---|---|---|---|---|---|---|')
        for r in rows:
            L.append('| %s | %d | %d | %d | %d | %d | %d | %d | %s |' % (
                r['pid'], r['cands'], r['n_facts'], r['with_sample'], r['ref'], r['ref_hit'], r['ref_hit_model_only'], r['one_shot_hit'], r['secs']))
    io.open(os.path.join(d, 'fine_fact_report.md'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')


def main():
    if wants_help():
        print(__doc__)
        return 0
    from shared.kernel.cli import positionals
    tag = opt('--tag') or 'u1'
    models = [m.strip() for m in (opt('--models') or opt('--model') or 'gemma3:1b').split(',') if m.strip()]
    zm = opt('--分区')
    run(tag, models, keys=positionals() or None, zone_model=zm)
    print('报告 →', os.path.join(paths.unit_study_dir(tag), 'fine_fact_report.md'))
    return 0


if __name__ == '__main__':
    main()
