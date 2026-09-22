# -*- coding: utf-8 -*-
"""论文类型画像（2026-09-22，待办 7）：这篇是哪一类 —— 合成 / 器件 / 机理 / 综述。

**为什么**：三件悬着的事都要先知道类型 —— 动作抽取要不要抓图注里的处理条件、精读按哪种权重选单元、阅读计划的第一个字段。
以前只有「是不是综述」一个硬猜（`sectioned.is_review_doc`：标题关键词 / 刊名表 / 无方法节且图多）。

做法（T2，qwen3.5:4b 一次四选一）：
    输入 = 标题 + 摘要（≤ 1500 字符）+ 骨架节名 + 图数 / 有无方法节（< 2k 字符）
    输出 = 一个词。答不出来或答词表外 → 退回旧硬猜（综述 / 非综述 → synthesis）。
    产物 = curated/<id>/profile.json（`paths.profile`），落地流水线一步做完，谁都能读。

四类的判据（写进提示词，也写在这给人看）：
    synthesis  做出新材料 / 新聚合物并报告它的性质（大多数材料论文）
    device     用材料做成器件或应用并考核器件指标（传感器、驱动器、电池、粘接件、涂层…）
    mechanism  机理 / 理论 / 模拟 / 表征方法学，不以新材料为主角
    review     综述

用法：python -m tools.deepread.profile KEY1 KEY2 [--model qwen3.5:4b]        判几篇，打印
      python -m tools.deepread.profile --范文 [--n 40]                         抽有范文的论文各判一次，列出来给人核
      python -m tools.deepread.profile KEY --落盘                              正式：写 profile.json
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

from shared.domain.schema import outline as _ol
from shared.kernel import catalog, paths
from shared.kernel.cli import flag, opt, wants_help

PRODUCER, VER = 'profile', 1
TYPES = ('synthesis', 'device', 'mechanism', 'review')
ZH = {'synthesis': '合成/材料', 'device': '器件/应用', 'mechanism': '机理/计算', 'review': '综述'}
NUM_CTX = 4096

SYS = ('Classify a materials-science paper into exactly ONE type:\n'
       'synthesis - reports making a new material or polymer and measures its properties\n'
       'device - builds a device or application from materials (sensor, actuator, battery, adhesive joint, coating, electronics) and evaluates device performance\n'
       'mechanism - mechanistic, theoretical, simulation or characterization-method study; no new material is the main subject\n'
       'review - reviews existing literature\n'
       'Reply with one word: synthesis, device, mechanism or review.')


def material(md, meta=None):
    """给模型看的那点东西：标题、摘要、节名、图数、有无方法节。"""
    meta = meta or {}
    o = _ol.build_outline(md or '')
    secs = o.get('sections') or []
    abstract = ''
    for s in secs:
        if s['kind'] == _ol.ABSTRACT:
            abstract = _ol.section_text(md, o, s['id'], with_subsections=False).strip()
            break
    if len(abstract) < 200:                      # 骨架没认出摘要：拿正文开头
        abstract = _ol.scan.clean_body(md or '')[:1500]
    names = [s['title'] for s in secs if s.get('title')][:25]
    kinds = {s['kind'] for s in secs}
    feats = {'n_figures': o.get('stats', {}).get('n_figures', 0), 'has_methods': bool(kinds & {_ol.SYNTHESIS, _ol.METHODS}),
             'n_sections': len(secs)}
    text = ('Title: %s\nJournal: %s\n\nAbstract: %s\n\nSection headings: %s\n\nFigures: %d. Methods/synthesis section: %s.' % (
        meta.get('title', ''), meta.get('journal', ''), re.sub(r'\s+', ' ', abstract)[:1500], ' | '.join(names) or '(none)',
        feats['n_figures'], 'yes' if feats['has_methods'] else 'no'))
    return text, feats, o


def fallback(meta, outline):
    from tools.deepread.sectioned import is_review_doc
    return 'review' if is_review_doc(meta.get('title', ''), outline, meta.get('journal', '')) else 'synthesis'


def classify(md, meta, chat, model):
    """→ {'type', 'raw', 'source': 'model'|'fallback', 'features'}。"""
    text, feats, o = material(md, meta)
    from tools.deepread.sectioned import _REVIEW_JOURNALS
    if any(j in (meta.get('journal') or '').lower() for j in _REVIEW_JOURNALS):   # 只登综述的刊物：不用问（40 篇实测 4B 把 Acc. Chem. Res. 判成合成）
        return {'type': 'review', 'raw': '', 'source': 'journal', 'features': feats}
    raw = ''
    try:
        raw = (chat(SYS, text, provider='ollama', model=model, temperature=0.0, max_tokens=8, num_ctx=NUM_CTX, thinking=False) or '').strip()
    except Exception as e:
        raw = 'ERR:' + str(e)[:80]
    word = re.sub(r'[^a-z]', '', raw.lower().split()[0] if raw.split() else '')
    hit = next((t for t in TYPES if word.startswith(t[:5])), None)
    if hit:
        return {'type': hit, 'raw': raw, 'source': 'model', 'features': feats}
    return {'type': fallback(meta, o), 'raw': raw, 'source': 'fallback', 'features': feats}


def classify_to_store(pid, model, log=print):
    from shared.adapters.llm_client import chat
    md = io.open(paths.fulltext(pid), encoding='utf-8').read()
    rec = catalog.record(pid)
    r = classify(md, rec, chat, model)
    r.update(by={'producer': PRODUCER, 'model': model, 'ver': VER, 'when': time.strftime('%Y-%m-%d')})
    io.open(paths.profile(pid), 'w', encoding='utf-8').write(json.dumps(r, ensure_ascii=False, indent=1))
    log('  %s：%s（%s）' % (pid, ZH[r['type']], r['source']))
    return r


def load(pid):
    p = paths.profile(pid)
    if not os.path.exists(p):
        return None
    try:
        return json.load(io.open(p, encoding='utf-8'))
    except Exception:
        return None


def main():
    if wants_help():
        print(__doc__)
        return 0
    from shared.kernel.cli import positionals
    from shared.adapters.llm_client import chat
    model = opt('--model') or 'qwen3.5:4b'
    keys = positionals()
    if flag('--范文'):
        n = int(opt('--n') or 40)
        keys = [k for k in catalog.ids() if os.path.exists(paths.reference(k)) and os.path.isfile(paths.fulltext(k))][:n]
    if flag('--落盘'):
        for k in keys:
            classify_to_store(k, model)
        return 0
    rows = []
    for k in keys:
        md = io.open(paths.fulltext(k), encoding='utf-8').read()
        rec = catalog.record(k)
        r = classify(md, rec, chat, model)
        rows.append({'pid': k, 'type': r['type'], 'raw': r['raw'], 'source': r['source'], 'title': rec.get('title', '')[:110],
                     'journal': rec.get('journal', ''), **r['features']})
        print('%-10s %-9s %s  [%s · 图 %d · 方法节 %s]  %s' % (r['type'], r['source'], k, rec.get('journal', '')[:24],
                                                          r['features']['n_figures'], 'Y' if r['features']['has_methods'] else 'N',
                                                          rec.get('title', '')[:100]))
    if flag('--范文'):
        out = os.path.join(paths.unit_study_dir('profile'), 'profile_%s.json' % model.replace(':', '-'))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        io.open(out, 'w', encoding='utf-8').write(json.dumps(rows, ensure_ascii=False, indent=1))
        print('→', out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
