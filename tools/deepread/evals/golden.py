# -*- coding: utf-8 -*-
"""金标评测的跑法（I/O 在这里，算分在 `scorers/golden.py`）。2026-09-15。

一轮 = 一个 `tag`（如 `v3_local_qwen3.5`）：从金标集里抽几篇，用当前的精读流程各跑一份
（产物放 `state/golden_eval/<tag>/<id>.html`，**不碰 curated 里的正式精读**），
逐篇对着范文打分，汇总成 `scores.json` + `report.md`。

改了模板 / 换了模型 → 换个 tag 再跑同一批 → 两份 report 并排看，哪一项升了哪一项降了一目了然。
`rescore(tag)` 只重新算分不重跑模型（改了评分口径时用）。
`baseline()` 把 curated 里已有的老精读（v2）当一轮打分，作为对照。

对外接口：
    candidates(need_si=False)             → 可评测的金标 id（有范文 + 已解析）
    sample(n, seed)                       → 固定抽样（同 seed 同批，跨轮可比）
    run(tag, keys, local, model, log)     → 跑 + 打分 + 报告
    rescore(tag)                          → 只重算分
    baseline(keys)                        → 老精读当一轮
"""
import io
import json
import os
import random
import time

from shared.kernel import catalog, paths
from tools.deepread.evals.scorers import golden as G


def candidates(need_si=False):
    """金标里能评的：有 reference.md、有 parsed/full.md 与 layout.json。"""
    try:
        idx = json.load(io.open(paths.golden_index(), encoding='utf-8'))
    except (OSError, ValueError):
        return []
    out = []
    for pid, rec in idx.items():
        if not (os.path.exists(paths.reference(pid)) and os.path.exists(paths.fulltext(pid))
                and os.path.exists(paths.layout(pid))):
            continue
        if need_si and not rec.get('si'):
            continue
        out.append(pid)
    return sorted(out)


def sample(n=10, seed=1, need_si=False):
    """固定抽样：同一个 seed 永远抽同一批，不同轮才能比。"""
    pool = candidates(need_si=need_si)
    rng = random.Random(seed)
    rng.shuffle(pool)
    return sorted(pool[:n])


def _score_one(pid, html_path):
    ours = G.text_of_html(io.open(html_path, encoding='utf-8').read())
    ref = G.text_of_reference(io.open(paths.reference(pid), encoding='utf-8').read())
    d = G.score(ours, ref)
    d['id'] = pid
    d['title'] = (catalog.read_meta(pid).get('title') or '')[:80]
    return d


def _write_report(tag, rows, meta):
    d = paths.golden_eval_dir(tag, create=True)
    agg = G.aggregate(rows)
    json.dump({'tag': tag, 'meta': meta, 'aggregate': agg, 'rows': rows},
              io.open(os.path.join(d, 'scores.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    lines = ['# 金标评测 · %s' % tag, '',
             '%s · %d 篇 · 评分口径 v%d' % (meta.get('when', ''), len(rows), G.GOLDEN_VER), '']
    if meta.get('note'):
        lines += [meta['note'], '']
    lines += ['| 指标 | 中位 |', '|---|---|']
    for k, label in (('composite', '综合分（0–100）'), ('skeleton', '骨架（/10）'), ('fig_two_para', '图两段'),
                     ('length_ratio', '篇幅比（目标 0.8–1.5）'), ('number_coverage', '数字覆盖'),
                     ('term_coverage', '术语覆盖'), ('q1_items', 'Q1 条数'), ('q2_items', 'Q2 条数'),
                     ('chars', '我们字数'), ('ref_chars', '范文字数')):
        lines.append('| %s | %s |' % (label, agg.get(k)))
    lines.append('| 通俗理解有的比例 | %s |' % agg.get('plain_rate'))
    lines += ['', '## 逐篇', '', '| id | 综合 | 骨架 | 图两段 | 篇幅比 | 数字 | 术语 | 漏的数 |', '|---|---|---|---|---|---|---|---|']
    for r in sorted(rows, key=lambda x: x['composite']):
        lines.append('| %s | %s | %s | %s | %s | %s | %s | %s |' % (
            r['id'], r['composite'], r['skeleton'], r['fig_two_para'], r['length_ratio'],
            r['number_coverage'], r['term_coverage'], '、'.join(r['numbers_missed'][:6])))
    io.open(os.path.join(d, 'report.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    return agg, os.path.join(d, 'report.md')


def run(tag, keys, local=False, model=None, log=print):
    """跑一轮：每篇用当前精读流程生成到评测目录，打分，出报告 → (汇总, 报告路径)。

    不写 curated/<id>/summary.html、不记状态库 —— 评测产物和正式产物分开。
    分栏缓存也另放（评测目录下），别跟正式精读串。
    """
    from tools.deepread import main_text
    d = paths.golden_eval_dir(tag, create=True)
    rows = []
    for i, pid in enumerate(keys, 1):
        out = os.path.join(d, pid + '.html')
        m = catalog.read_meta(pid)
        log('[%d/%d] %s %s' % (i, len(keys), pid, (m.get('title') or '')[:50]))
        if not os.path.exists(out):
            t0 = time.time()
            try:
                main_text.read_main(paths.parsed_dir(pid), out, log=lambda *a: None,
                                    title=m.get('title'), doi=m.get('doi') or m.get('DOI'),
                                    paper_key=pid, local=local, model=model)
                log('  %.0f s' % (time.time() - t0))
            except Exception as e:
                log('  [失败] %s' % str(e)[:160])
                continue
        r = _score_one(pid, out)
        rows.append(r)
        log('  综合 %s · 骨架 %d/10 · 图两段 %s · 篇幅比 %s · 数字覆盖 %s · 术语 %s' % (
            r['composite'], r['skeleton'], r['fig_two_para'], r['length_ratio'],
            r['number_coverage'], r['term_coverage']))
    meta = {'when': time.strftime('%Y-%m-%d %H:%M'), 'local': local, 'model': model or '',
            'prompt_ver': main_text.PROMPT_VER, 'keys': list(keys)}
    return _write_report(tag, rows, meta)


def rescore(tag):
    """评分口径变了：只重算这一轮已有的 HTML，不重跑模型。"""
    d = paths.golden_eval_dir(tag)
    old = {}
    try:
        old = json.load(io.open(os.path.join(d, 'scores.json'), encoding='utf-8'))
    except (OSError, ValueError):
        pass
    rows = []
    for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if n.endswith('.html'):
            pid = n[:-5]
            if os.path.exists(paths.reference(pid)):
                rows.append(_score_one(pid, os.path.join(d, n)))
    meta = dict(old.get('meta') or {}, rescored=time.strftime('%Y-%m-%d %H:%M'))
    return _write_report(tag, rows, meta)


def baseline(keys, tag='v2_baseline'):
    """curated 里已有的老精读（一次调用的 v2）当一轮打分，作为对照。没有的跳过。"""
    rows = []
    for pid in keys:
        p = paths.summary(pid)
        if os.path.exists(p):
            rows.append(_score_one(pid, p))
    return _write_report(tag, rows, {'when': time.strftime('%Y-%m-%d %H:%M'),
                                     'note': '对照组：curated 里已有的老精读（main@v2 一次调用）', 'keys': list(keys)})
