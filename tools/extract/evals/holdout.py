# -*- coding: utf-8 -*-
"""考卷评分：字段级抽取（fine_fact）的产物 vs 考卷金标（golden/measurements_holdout.json）。

**为什么有它**（2026-09-24）：之前的尺子是「范文数命中率」—— 量的是「和公众号作者挑的数重不重合」，
混着主观取舍、看图写的数与范文自己的错；而且调规则和报数用的是同一批 10 篇（练习集 70% → 考卷 44%）。
这里换成**全量金标**（正文里本文材料的每个性能数都标了，另有 edge / negative 两档），算的是：

    召回率   该抽的（core）抽到几成
    准确率   抽出来的里面几成是该抽的（core + edge）
    错标率   数对、样品对，但性质名标错
    硬错误   抽到了明确不该抽的（别人文献的数、条件、谱峰、志愿者数据）

**只算正文**：金标只覆盖 `parsed/full.md` 正文（不含表格与 SI），所以只拿 `where == 'main'` 的抽取结果来比。

用法：python -m tools.extract.evals.holdout [--tag u1] [--model qwen3.5:4b] [--gold holdout|dev]
     读 data/state/unit_study/<tag>/fine_fact_<model>_<篇>.json（fine_fact 跑考卷时写的），不调模型、不花钱。
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

from shared.kernel import paths
from shared.kernel.cli import opt, wants_help
from tools.extract.evals.scorers.measurements import score_paper

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden')
GOLDS = {'holdout': os.path.join(_DIR, 'measurements_holdout.json'),   # 考卷：只报数
         'dev': os.path.join(_DIR, 'measurements.json')}               # 练习集：调规则时看错例
GOLD = GOLDS['holdout']


def load_gold(which='holdout'):
    return json.load(io.open(GOLDS[which], encoding='utf-8'))['papers']


def rows_from_facts(facts):
    """fine_fact 的事实 → 评分器要的行（只留正文）。"""
    rows = []
    for f in facts or []:
        if f.get('where', 'main') != 'main':
            continue
        try:
            v = float(f.get('norm'))
        except (TypeError, ValueError):
            continue
        rows.append({'sample_id': f.get('sample') or '', 'name': f.get('property') or '', 'value': v,
                     'unit': f.get('unit') or ''})
    return rows


def facts_file(tag, model, key):
    return os.path.join(paths.unit_study_dir(tag), 'fine_fact_%s_%s.json' % (re.sub(r'[^A-Za-z0-9.-]+', '-', model), key))


def summarize(scores):
    """各篇合计：召回 = Σ命中 core / Σcore；准确率 = Σ好 / Σ抽出。"""
    n_core = sum(s['n_core'] for s in scores)
    hit = sum(round((s['recall'] or 0) * s['n_core']) for s in scores)
    n_rows = sum(s['n_rows'] for s in scores)
    good = sum(round((s['precision'] or 0) * s['n_rows']) for s in scores)
    mis = sum(len(s['mislabeled']) for s in scores)
    hard = sum(s['n_hard_errors'] for s in scores)
    return {'n_papers': len(scores), 'n_core': n_core, 'recall': hit / n_core if n_core else None,
            'n_rows': n_rows, 'precision': good / n_rows if n_rows else None,
            'mislabeled': mis, 'hard_errors': hard}


def run(tag='u1', model='qwen3.5:4b', log=print, which='holdout'):
    scores = []
    for g in load_gold(which):
        p = facts_file(tag, model, g['key'])
        if not os.path.exists(p):
            log('%s：没有抽取结果（%s）' % (g['key'], p))
            continue
        facts = json.load(io.open(p, encoding='utf-8')).get('facts') or []
        s = score_paper(g, rows_from_facts(facts))
        scores.append(s)
        log('%-40s 召回 %s · 准确 %s · 错标 %d · 硬错误 %d（抽出 %d 条，core %d）' % (
            g['key'], _pct(s['recall']), _pct(s['precision']), len(s['mislabeled']), s['n_hard_errors'], s['n_rows'], s['n_core']))
    agg = summarize(scores)
    log('合计 %d 篇：召回 %s · 准确 %s · 错标 %d · 硬错误 %d（抽出 %d 条，core %d）' % (
        agg['n_papers'], _pct(agg['recall']), _pct(agg['precision']), agg['mislabeled'], agg['hard_errors'], agg['n_rows'], agg['n_core']))
    return agg, scores


def _pct(x):
    return '-' if x is None else '%.0f%%' % (100 * x)


def main():
    if wants_help():
        print(__doc__)
        return 0
    run(opt('--tag') or 'u1', opt('--model') or 'qwen3.5:4b', which=opt('--gold') or 'holdout')
    return 0


if __name__ == '__main__':
    sys.exit(main())
