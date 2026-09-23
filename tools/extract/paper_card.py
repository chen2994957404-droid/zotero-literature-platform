# -*- coding: utf-8 -*-
"""paper_card · 整篇卡片：材料体系 / 动态键家族 / 自修复 / 核心发现 / 局限（2026-09-23，规划 §十五 第 3 步后半）。

**为什么**：数值、原料、合成条件已经由单元库（fine_fact / fine_action）接手；老的整篇抽取（`extract.run`，
一次把全文塞给大模型填 11 个字段）剩下的用处只有**整篇级**那几项 —— 概念矩阵靠 `dynamic_bond_type`，
对比表靠 `material_system` / `key_finding`。这几项不需要读全文：标题 + 摘要 + 结论就答得出，是小模型的形状。

做法（跟 profile / fine_fact 同一套路：小模型只答小题，脚本核对）：
    材料 = 标题 + 摘要 + 结论（各 ≤ 1500 字符）
    ① 模型 从固定的键家族名单里选（答名字，不答序号）→ ② 脚本 只留**材料里有对应关键词**的家族（`schema.bond_families`）
    ③ 模型 短 JSON：material_system / self_healing / key_finding / limitation
    ④ 脚本 material_system 至少一个实词在材料里；key_finding 里的数必须在材料里（`numcheck.ungrounded_numbers`），不在就丢
    doc_type 读 profile.json（综述 → review），没有就空
产物 `curated/<id>/card.json`（`paths.card`）。paperdb 对**没有老整篇抽取记录**的文献用它补上整篇级字段。

用法：python -m tools.extract.paper_card KEY1 KEY2 [--model qwen3.5:4b]     判几篇，打印
      python -m tools.extract.paper_card --对照 [--n 20]                    跟老整篇抽取（structured/*.json）逐篇对比键家族
      python -m tools.extract.paper_card KEY --落盘                         正式：写 card.json
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

from shared.domain import numcheck as _nums
from shared.domain import schema
from shared.domain.schema import outline as _ol
from shared.kernel import catalog, paths
from shared.kernel.cli import flag, opt, positionals, wants_help

PRODUCER, VER = 'paper_card', 1
NUM_CTX = 4096
CAP = 1500

# 家族名（中文，与 schema.BOND_FAMILIES 同序）→ 给模型看的英文名。英文名自己必须被该家族的正则认出（selftest 查）
BOND_EN = {
    '氢键': 'hydrogen bond',
    'B–O 硼氧': 'boroxine or borate B-O bond',
    '硼酸酯': 'boronic ester',
    '金属配位': 'metal coordination',
    '二硫键': 'disulfide',
    '亚胺/席夫碱': 'imine',
    'Diels–Alder': 'Diels-Alder',
    '离子/静电': 'ionic or electrostatic interaction',
    'π–π/主客体': 'pi-pi stacking or host-guest',
    '酯/氨酯交换': 'transesterification or vitrimer exchange',
    '相分离/结晶': 'phase separation or crystalline domains',
}

SYS_BONDS = ('You read the title, abstract and conclusion of a materials paper. Which reversible or dynamic interactions '
             'does the paper use to build its material (for crosslinking, healing, reprocessing or energy dissipation)? '
             'Choose only from this list:\n%s\n'
             'Reply with the chosen names separated by semicolons, copied exactly. Reply none if the paper uses none of them.')

SYS_CARD = ('You read the title, abstract and conclusion of a materials paper. Fill this JSON, copying wording from the text '
            'where possible:\n'
            '{"material_system": "core material in at most 15 words",\n'
            ' "self_healing": "yes: mechanism in at most 15 words" or "no",\n'
            ' "key_finding": "the single most important finding in one sentence",\n'
            ' "limitation": "a limitation the authors state, one sentence, or N/A"}\n'
            'Use only what the text says.')


def material(md, meta=None):
    """标题 + 摘要 + 结论。骨架认不出摘要就拿正文开头。"""
    meta = meta or {}
    o = _ol.build_outline(md or '')
    parts = {}
    for s in o.get('sections') or []:
        if s['kind'] in (_ol.ABSTRACT, _ol.CONCLUSION) and s['kind'] not in parts:
            parts[s['kind']] = _ol.section_text(md, o, s['id'], with_subsections=False).strip()
    abstract = parts.get(_ol.ABSTRACT, '')
    if len(abstract) < 200:
        abstract = _ol.scan.clean_body(md or '')[:CAP]
    return 'Title: %s\n\nAbstract: %s\n\nConclusion: %s' % (
        meta.get('title', ''), re.sub(r'\s+', ' ', abstract)[:CAP],
        re.sub(r'\s+', ' ', parts.get(_ol.CONCLUSION, ''))[:CAP] or '(none)')


def pick_bonds(answer, text):
    """模型答的家族名 → 家族列表，只留材料里有对应关键词的。返回 (留下的, 被脚本拿掉的)。"""
    ans = (answer or '').lower()
    chosen = [zh for zh, en in BOND_EN.items() if en.lower() in ans or zh.lower() in ans]
    evidence = set(schema.bond_families(text))
    return [b for b in chosen if b in evidence], [b for b in chosen if b not in evidence]


def check_card(card, text):
    """脚本核对：material_system 至少一个实词（≥4 字母）在材料里；key_finding 里的数都要在材料里。不过关的字段清空。"""
    checks = {}
    low = (text or '').lower()
    ms = str(card.get('material_system') or '').strip()
    words = [w for w in re.findall(r'[A-Za-z][A-Za-z\-]{3,}', ms)]
    checks['material_system_grounded'] = bool(words) and any(w.lower() in low for w in words)
    if not checks['material_system_grounded']:
        card['material_system'] = ''
    kf = str(card.get('key_finding') or '').strip()
    bad = _nums.ungrounded_numbers(kf, text) if kf else []
    checks['key_finding_numbers_ok'] = not bad
    if bad:
        card['key_finding'] = ''
    sh = str(card.get('self_healing') or '').strip()
    card['self_healing'] = sh if sh.lower().startswith(('yes', 'no')) else ''
    lim = str(card.get('limitation') or '').strip()
    card['limitation'] = lim or 'N/A'
    return card, checks


def make_card(md, meta, chat, chat_json, model, doc_type=''):
    """一篇 → 卡片 dict（不落盘）。"""
    text = material(md, meta)
    names = '\n'.join(BOND_EN.values())
    raw_bonds = ''
    try:
        raw_bonds = (chat(SYS_BONDS % names, text, provider='ollama', model=model, temperature=0.0,
                          max_tokens=60, num_ctx=NUM_CTX, thinking=False) or '').strip()
    except Exception as e:
        raw_bonds = 'ERR:' + str(e)[:80]
    bonds, dropped = pick_bonds(raw_bonds, text)
    try:
        d = chat_json(SYS_CARD, text, provider='ollama', model=model, num_ctx=NUM_CTX) or {}
    except Exception:
        d = {}
    card = {k: d.get(k, '') for k in ('material_system', 'self_healing', 'key_finding', 'limitation')}
    card, checks = check_card(card, text)
    checks['bonds_dropped_no_evidence'] = dropped
    card.update(
        dynamic_bond_type='; '.join(BOND_EN[b] for b in bonds) if bonds else ('none' if raw_bonds.lower().startswith('none') else ''),
        bond_families=bonds, doc_type=doc_type, raw_bonds=raw_bonds[:200], checks=checks)
    return card


def _doc_type(pid):
    p = paths.profile(pid)
    try:
        t = json.load(io.open(p, encoding='utf-8')).get('type') if os.path.exists(p) else ''
    except Exception:
        t = ''
    return 'review' if t == 'review' else ('research' if t else '')


def card_to_store(pid, model, log=print):
    from shared.adapters.llm_client import chat, chat_json
    md = io.open(paths.fulltext(pid), encoding='utf-8').read()
    rec = catalog.record(pid)
    c = make_card(md, rec, chat, chat_json, model, doc_type=_doc_type(pid))
    c['by'] = {'producer': PRODUCER, 'model': model, 'ver': VER, 'when': time.strftime('%Y-%m-%d')}
    io.open(paths.card(pid), 'w', encoding='utf-8').write(json.dumps(c, ensure_ascii=False, indent=1))
    log('  %s：%s · %s' % (pid, '、'.join(c['bond_families']) or '无动态键', c['material_system'][:60]))
    return c


def load(pid):
    p = paths.card(pid)
    if not os.path.exists(p):
        return None
    try:
        return json.load(io.open(p, encoding='utf-8'))
    except Exception:
        return None


def compare(keys, model, log=print):
    """跟老整篇抽取逐篇比键家族。返回汇总 dict。"""
    from shared.adapters.llm_client import chat, chat_json
    agg: dict = {'n': 0, 'same': 0, 'overlap': 0, 'differ': 0, 'card_only': 0, 'old_only': 0, 'both_empty': 0}
    rows = []
    for k in keys:
        try:
            old = json.load(io.open(paths.structured(k), encoding='utf-8'))
            md = io.open(paths.fulltext(k), encoding='utf-8').read()
        except Exception:
            continue
        rec = catalog.record(k)
        t0 = time.time()
        c = make_card(md, rec, chat, chat_json, model, doc_type=_doc_type(k))
        a, b = set(c['bond_families']), set(schema.bond_families(str(old.get('dynamic_bond_type') or '')))
        agg['n'] += 1
        tag = ('both_empty' if not a and not b else 'same' if a == b else 'overlap' if a & b
               else 'card_only' if not b else 'old_only' if not a else 'differ')
        agg[tag] += 1
        rows.append({'key': k, 'tag': tag, 'card': sorted(a), 'old': sorted(b), 'secs': round(time.time() - t0, 1),
                     'ms_card': c['material_system'], 'ms_old': str(old.get('material_system') or '')[:120],
                     'dropped': c['checks']['bonds_dropped_no_evidence'], 'raw_bonds': c['raw_bonds'],
                     'old_bond_text': str(old.get('dynamic_bond_type') or '')[:120]})
        log('%-9s %s  卡片 %s | 老 %s  (%.0fs)\n    材料：%s\n    老材料：%s\n    老键原文：%s' % (
            tag, k, '、'.join(sorted(a)) or '-', '、'.join(sorted(b)) or '-', time.time() - t0,
            c['material_system'][:90], rows[-1]['ms_old'][:90], rows[-1]['old_bond_text'][:90]))
    agg['rows'] = rows
    return agg


def main():
    if wants_help():
        print(__doc__)
        return 0
    model = opt('--model') or 'qwen3.5:4b'
    keys = positionals()
    if flag('--对照'):
        n = int(opt('--n') or 20)
        keys = keys or [k for k in catalog.ids() if os.path.isfile(paths.structured(k)) and os.path.isfile(paths.fulltext(k))][:n]
        agg = compare(keys, model)
        print('\n%d 篇：一致 %d · 有交集 %d · 完全不同 %d · 只卡片有 %d · 只老的有 %d · 都空 %d' % (
            agg['n'], agg['same'], agg['overlap'], agg['differ'], agg['card_only'], agg['old_only'], agg['both_empty']))
        out = os.path.join(paths.unit_study_dir('paper_card'), 'compare_%s.json' % model.replace(':', '-'))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        io.open(out, 'w', encoding='utf-8').write(json.dumps(agg, ensure_ascii=False, indent=1))
        print('→', out)
        return 0
    if flag('--落盘'):
        for k in keys:
            card_to_store(k, model)
        return 0
    from shared.adapters.llm_client import chat, chat_json
    for k in keys:
        md = io.open(paths.fulltext(k), encoding='utf-8').read()
        c = make_card(md, catalog.record(k), chat, chat_json, model, doc_type=_doc_type(k))
        print(json.dumps({'key': k, **c}, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
