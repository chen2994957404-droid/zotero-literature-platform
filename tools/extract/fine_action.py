# -*- coding: utf-8 -*-
"""fine_action · 合成动作（制备步骤）的**字段级拆分抽取**（2026-09-22，待办 4e）。

跟 `fine_fact` 同一套路：脚本找句子、脚本切从句、小模型只填固定槽位、脚本逐字核对，
不让小模型「自己找步骤」。

    ① 脚本   正文方法节 + SI 全文 → 切句（pySBD）→ 有制备动词（added / stirred / cured…）且不是仪器句的才算候选（T0）
    ② 脚本   一句里「, and / then / followed by」连着两个动作的，切成两条从句（T0）
    ③ 模型   一条从句 → 五个槽位：action / materials / amounts / conditions / product，**只许抄句子里的词**（T2）
    ④ 脚本   核对：amounts / conditions 里的数必须在这句里；materials 每个名字必须在这句里；不在的整个扔掉（T0）
    ⑤ 脚本   order = 句子顺序；落库为 action 单元（shared.kernel.units_store）

标尺：单元研究里范文的 action 单元（`data/state/unit_study/<tag>/<pid>.json`）—— 范文是中文，
按**数**比：范文动作里的投料量 / 条件数字有几成出现在我们抽出的 amounts / conditions 里（跟 fine_fact 的「范文数命中」同一口径）。

用法：python -m tools.extract.fine_action KEY1 KEY2 --model qwen3.5:4b [--tag u1]     试跑 + 对标尺
      python -m tools.extract.fine_action KEY1 --落库 --model qwen3.5:4b                正式入口：动作 → curated/<id>/units.json
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
from shared.domain.schema import scan
from shared.adapters import sentences as _sentences
from shared.kernel import paths
from shared.kernel.cli import flag, opt, wants_help

PRODUCER, VER = 'fine_action', 1
NUM_CTX = 2048
PARALLEL = 4
MAX_STEPS = 120         # 一篇最多问这么多条从句（SI 长的合成节能有几百句，先封顶）

_VERB = (r'add(?:ed)?|dissolv(?:ed|e)|stir(?:red)?|mix(?:ed)?|heat(?:ed)?|cool(?:ed)?|pour(?:ed)?|cast|cur(?:ed|e)|dr(?:ied|y)|'
         r'wash(?:ed)?|precipitat(?:ed|e)|filter(?:ed)?|degas(?:sed)?|react(?:ed)?|reflux(?:ed)?|purg(?:ed|e)|sonicat(?:ed|e)|'
         r'centrifug(?:ed|e)|evaporat(?:ed|e)|remov(?:ed|e)|charg(?:ed|e)|transfer(?:red)?|purif(?:ied|y)|dialy[sz](?:ed|e)|'
         r'freeze-dried|anneal(?:ed)?|(?:hot-)?press(?:ed)?|mold(?:ed)?|immers(?:ed|e)|soak(?:ed)?|coat(?:ed)?|spin-coat(?:ed)?|'
         r'synthesi[sz](?:ed|e)|prepar(?:ed|e)|polymeri[sz](?:ed|e)|cross-?link(?:ed)?|quench(?:ed)?|dilut(?:ed|e)|'
         r'suspend(?:ed)?|swell(?:ed)?|swollen|extrud(?:ed|e)|lyophili[sz](?:ed|e)|extract(?:ed)?|neutrali[sz](?:ed|e)|'
         r'incubat(?:ed|e)|seal(?:ed)?|kept|maintain(?:ed)?|allow(?:ed)? to|left to|obtain(?:ed)?|yield(?:ed|ing)?|afford(?:ed)?')
_STEP_RE = re.compile(r'\b(?:was|were|is|are|then|and|subsequently|finally|first)\s+(?:%s)\b|\b(?:%s)\s+(?:in|into|with|at|for|under|to)\b' % (_VERB, _VERB), re.I)
_INSTR_RE = re.compile(r'\b(spectra|spectrum|spectromet\w*|diffractomet\w*|microscop\w*|rheomet\w*|analy[sz]er|instrument\w*|'
                       r'(?:were|was) (?:recorded|measured|characterized|performed|conducted|carried out|collected|obtained|acquired|imaged) (?:on|with|using|by)|'
                       r'tensile test\w*|DSC|TGA|DMA|SEM|TEM|AFM|XRD|FTIR|FT-IR|NMR|GPC|UV-vis)\b', re.I)
_QTY_RE = re.compile(r'\d+(?:\.\d+)?\s*(?:g|mg|kg|mL|ml|L|μL|µL|uL|mmol|mol|M|wt|vol|mol ?%|%|°C|℃|K|h|hr|hours?|min|s|rpm|MPa|kPa|bar|Pa|nm|μm|mm|cm|W|V|eq|equiv)\b')
_SPLIT_RE = re.compile(r',\s*(?=(?:and|then|followed by|after which|before)\s+\w)|;\s+|\.\s+(?=Then\b|Subsequently\b|Afterwards\b|Finally\b)', re.I)
_NUM_RE = re.compile(r'\d+(?:\.\d+)?')
_SUPPLY_RE = re.compile(r'purchased|obtained from|supplied by|provided by|used as received|without further purification', re.I)
_PRODUCT_RE = re.compile(r'\b(?:to (?:obtain|afford|yield|give|form|produce)|yielding|affording|giving|obtaining|resulting in|was obtained as|to get)\s+(?:the\s+|a\s+|an\s+)?([A-Za-z][^,.;()]{2,60}?)(?=[,.;(]|\s+(?:as|in|with|after)\b|$)', re.I)

SYS = ('One sentence from the experimental section of a materials paper is given. It describes a preparation step. '
       'Fill five slots using ONLY words copied from the sentence. If a slot is not stated, write none. '
       'Format exactly, one slot per line:\n'
       'action: <the main verb phrase>\n'
       'materials: <substances used, comma-separated>\n'
       'amounts: <quantities with units, comma-separated>\n'
       'conditions: <temperature, time, atmosphere, speed, solvent, comma-separated>\n'
       'product: <what is obtained>')


def _drop_nonbody(md):
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


def _methods_text(md):
    """正文里的方法 / 合成节；认不出来就整个正文（候选筛选靠句子本身的长相）。"""
    from shared.domain.schema import outline as _ol
    o = _ol.build_outline(md)
    parts = [md[s['start']:s['end']] for s in o.get('sections') or [] if s['kind'] in (_ol.SYNTHESIS, _ol.METHODS)]
    return '\n\n'.join(parts) if sum(len(p) for p in parts) >= 500 else _drop_nonbody(md)


def is_step(sent):
    """像制备步骤：有制备动词，不是仪器 / 测试句，且有量或化学品样的词。"""
    if len(sent) < 25 or len(sent) > 700 or not _STEP_RE.search(sent):
        return False
    if _INSTR_RE.search(sent) and not _QTY_RE.search(sent):
        return False
    if _SUPPLY_RE.search(sent) and not _QTY_RE.search(sent):      # 「购自 Aldrich、用前未处理」是原料来源，不是步骤
        return False
    return True


def clauses(sent):
    """一句拆成动作从句：只在拆出来的每一半都有制备动词时才拆。"""
    parts = [p.strip() for p in _SPLIT_RE.split(sent) if p and p.strip()]
    if len(parts) <= 1:
        return [sent]
    out, buf = [], ''
    for p in parts:
        cand = (buf + ', ' + p) if buf else p
        if _STEP_RE.search(p) and buf and _STEP_RE.search(buf):
            out.append(buf)
            buf = p
        else:
            buf = cand
    if buf:
        out.append(buf)
    return out


def _unwrap(text):
    """MineRU 的硬换行会把「12\nh」「Temperatu\nre」切开，pySBD 又在换行处断句 → 条件丢单位、句子只剩半截。
    段内单个换行：两边都是小写字母就是词被切开（直接接上），否则当空格。"""
    text = re.sub(r'(?<=[a-z])\n(?=[a-z])', '', text)
    return re.sub(r'(?<!\n)\n(?!\n)', ' ', text)


def candidates(md, si_md=''):
    """[(where, 句序, 从句)]：正文方法节 + SI 全文里像步骤的句子，切从句，封顶 MAX_STEPS。"""
    out = []
    for where, text in (('main', _methods_text(md) if md else ''), ('si', _drop_nonbody(si_md) if si_md else '')):
        text = _unwrap(scan.clean_body(text))
        for i, (_, _, s) in enumerate(_sentences.split(text)):
            s = ' '.join(s.split())
            if is_step(s):
                for c in clauses(s):
                    if _STEP_RE.search(c):
                        out.append((where, i, c))
    return out[:MAX_STEPS]


def _parse(raw):
    d = {}
    for ln in (raw or '').splitlines():
        m = re.match(r'\s*(action|materials|amounts|conditions|product)\s*:\s*(.*)', ln, re.I)
        if m:
            v = m.group(2).strip().strip('`"\'')
            d[m.group(1).lower()] = '' if v.lower() in ('none', 'n/a', 'not stated', '-', '') else v
    return d


def _in(sent, phrase):
    return phrase and ' '.join(phrase.split()).lower() in ' '.join(sent.split()).lower()


def verify(sent, d):
    """逐槽核对：数不在句里的量 / 条件项扔掉；名字不在句里的材料扔掉；动作不在句里就用正则找到的动词。"""
    sl = sent.lower()
    out = {'action': d.get('action', ''), 'materials': [], 'amounts': [], 'conditions': [], 'product': d.get('product', '')}
    if not _in(sent, out['action']):
        m = _STEP_RE.search(sent)
        out['action'] = m.group(0).strip() if m else ''
    for k in ('amounts', 'conditions'):
        for item in re.split(r',\s+(?![^()]*\))', d.get(k, '')):
            item = item.strip()
            if not item:
                continue
            nums = _NUM_RE.findall(item)
            if nums and all(n in sl for n in nums) or (not nums and _in(sent, item)):
                out[k].append(item)
    for m_ in re.split(r',\s+(?![^()]*\))', d.get('materials', '')):
        m_ = m_.strip()
        if m_ and _in(sent, m_) and len(m_) <= 80:
            out['materials'].append(m_)
    if out['product'] and not _in(sent, out['product']):
        pm = _PRODUCT_RE.search(sent)
        out['product'] = pm.group(1).strip() if pm else ''
    return out


def _ask(chat, sent, model):
    try:
        raw = chat(SYS, 'Sentence: ' + sent, provider='ollama', model=model, temperature=0.0, max_tokens=160,
                   num_ctx=NUM_CTX, thinking=False)
    except Exception:
        return None
    return _parse(raw)


def extract_paper(md, chat, model, log=print, si_md=''):
    """一篇 → 动作列表 + 统计。"""
    t0 = time.time()
    cands = candidates(md, si_md)
    stats = {'cands': len(cands), 'no_answer': 0, 'empty': 0, 'secs': 0.0}
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        answers = list(pool.map(lambda c: _ask(chat, c[2], model), cands))
    steps = []
    for (where, i, sent), d in zip(cands, answers):
        if d is None:
            stats['no_answer'] += 1
            continue
        v = verify(sent, d)
        if not v['action'] or not (v['materials'] or v['amounts'] or v['conditions'] or v['product']):
            stats['empty'] += 1
            continue
        steps.append({'where': where, 'order': len(steps) + 1, 'sent': sent, **v})
    stats['secs'] = round(time.time() - t0, 1)
    return steps, stats


def to_units(steps, model):
    from shared.kernel import units_store
    by = {'producer': PRODUCER, 'model': model, 'ver': VER, 'when': time.strftime('%Y-%m-%d')}
    out = []
    for s in steps:
        try:
            out.append(units_store.make_unit('action', {'action': s['action'], 'materials': s['materials'],
                                                        'amounts': ', '.join(s['amounts']), 'conditions': ', '.join(s['conditions']),
                                                        'product': s['product'], 'order': str(s['order'])},
                                             {'where': s['where'], 'quote': s['sent']}, by, {'verified': True}))
        except ValueError:
            continue
    return out


def extract_to_store(pid, model, log=print):
    from shared.adapters.llm_client import chat
    from shared.kernel import units_store
    md = io.open(paths.fulltext(pid), encoding='utf-8').read()
    sp = paths.si_fulltext(pid)
    si = io.open(sp, encoding='utf-8').read() if os.path.exists(sp) else ''
    steps, st = extract_paper(md, chat, model, log, si_md=si)
    units = to_units(steps, model)
    merged = units_store.merge(pid, units, producer=PRODUCER)
    log('  %s：%d 条动作入库（库里现有 %s）· %ss' % (pid, len(units), units_store.stats(merged), st['secs']))
    return len(units), paths.units(pid)


# ── 标尺 ──

def ref_numbers(pid, tag):
    """范文 action 单元的 amounts / conditions 里的数（≥2 位，去掉 10/20/100 这种随处可见的）。"""
    p = os.path.join(paths.unit_study_dir(tag), pid + '.json')
    if not os.path.exists(p):
        return set()
    out = set()
    for u in json.load(io.open(p, encoding='utf-8'))['units']:
        if u.get('type') == 'action':
            for x in _NUM_RE.findall(str(u.get('amounts', '')) + ' ' + str(u.get('conditions', ''))):
                if len(x) >= 2 and x not in ('10', '20', '100'):
                    out.add(_nums.norm(x))
    return out


def _nums_of(steps):
    return {_nums.norm(x) for s in steps for x in _NUM_RE.findall(' '.join(s['amounts'] + s['conditions']))}


def main():
    if wants_help():
        print(__doc__)
        return 0
    from shared.kernel.cli import positionals
    from shared.adapters.llm_client import chat
    model = opt('--model') or 'qwen3.5:4b'
    tag = opt('--tag')
    keys = positionals()
    if flag('--落库'):
        for pid in keys:
            n, path = extract_to_store(pid, model)
            print('%s → %d 条 → %s' % (pid, n, path))
        return 0
    rows = []
    for pid in keys:
        md = io.open(paths.fulltext(pid), encoding='utf-8').read()
        sp = paths.si_fulltext(pid)
        si = io.open(sp, encoding='utf-8').read() if os.path.exists(sp) else ''
        steps, st = extract_paper(md, chat, model, print, si_md=si)
        print('[%s] 候选 %d → 动作 %d（无答 %d、空 %d）· %ss' % (pid, st['cands'], len(steps), st['no_answer'], st['empty'], st['secs']))
        for s in steps[:400]:
            print('  #%d [%s] %s | 材料 %s | 量 %s | 条件 %s | 产物 %s' % (
                s['order'], s['where'], s['action'], '、'.join(s['materials']), '、'.join(s['amounts']), '、'.join(s['conditions']), s['product']))
            print('      ← ' + s['sent'][:160])
        row = {'pid': pid, 'cands': st['cands'], 'steps': len(steps), 'secs': st['secs']}
        if tag:
            ref = ref_numbers(pid, tag)
            cand_nums = {_nums.norm(x) for _, _, c in candidates(md, si) for x in _NUM_RE.findall(c)}
            row.update(ref=len(ref), hit=len(ref & _nums_of(steps)), ceiling=len(ref & cand_nums))
            print('  范文动作数 %d · 命中 %d · 候选上限 %d' % (row['ref'], row['hit'], row['ceiling']))
        rows.append(row)
    if tag and rows:
        d = paths.unit_study_dir(tag)
        os.makedirs(d, exist_ok=True)
        io.open(os.path.join(d, 'fine_action_%s.json' % model.replace(':', '-')), 'w', encoding='utf-8').write(
            json.dumps(rows, ensure_ascii=False, indent=1))
        tr, th, tc = sum(r['ref'] for r in rows), sum(r['hit'] for r in rows), sum(r['ceiling'] for r in rows)
        print('合计：范文动作数 %d · 命中 %d（%.0f%%）· 候选上限 %d（%.0f%%）' % (tr, th, 100.0 * th / max(1, tr), tc, 100.0 * tc / max(1, tr)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
