# -*- coding: utf-8 -*-
"""正文数值抽取的评分器：**抽出来的一批数** vs **人工金标**。纯函数、不联网。

金标与范围定义见 `../golden/measurements_README.md`。这里只回答四个问题：

| 指标 | 意思 |
|---|---|
| 召回率 | 该抽的（core）抽到了几成 |
| 准确率 | 抽出来的里面有几成是该抽的（core + edge） |
| **错标率** | 数值对、样品对，但**性能名标错**的比例 |
| **硬错误** | 抽到了明确不该抽的（negative）—— 别人文献的数、条件、谱峰 |

**为什么要把「错标」单拎出来**（2026-09-08 的实测教训）：同一个 `43.1 MPa`，
一个模型标成 `young's modulus`、另一个标成 `tensile strength`，
**至少一个是错的，而「数字在原文里」这条校验对两者都满分**。
错标进了库最阴 —— 它长得跟真数据一模一样，还会被拿去比大小。
"""

import re

_REL_TOL = 0.01          # 数值相对误差 1% 以内算同一个数（排版会带来 ±1 位有效数字）


def _same_value(a, b):
    """两个数是不是同一个。相对误差 1%；其中一个是 0 时退回绝对比较。"""
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if a == b:
        return True
    scale = max(abs(a), abs(b))
    return scale > 0 and abs(a - b) / scale <= _REL_TOL


def _norm(s):
    return ' '.join(str(s or '').lower().replace('_', ' ').split())


def _same_sample(a, b, single=False):
    """样品名对得上吗。**只做大小写与空白归一**，不做模糊匹配 ——
    模糊匹配会把 `SPU` 和 `SPU/10D-SiO2` 算成一个，那正是最该抓的错。

    `single=True`（金标标了 `single_sample`）时**不比样品**：全篇只有一个体系时，
    正文报数值本来就不指明样品，模型答 `unknown` 是正确行为。
    2026-09-08 实测：不放行这一条，P2Q5TYFR 四条全对的答案会被判成 0 分。
    多体系论文里样品归属恰恰是最该考的一项，所以这个放行**由金标逐篇声明**，
    不是全局放水。
    """
    if single:
        return True
    x, y = _norm(a), _norm(b)
    if x == y and x:
        return True
    # `1` vs `Polymer 1`、`PBS` vs `PBS 1` 不算 —— 后者是不同样品。
    # 只放行「金标写全名、模型写论文里的短名」这一种：一端是另一端的完整词
    return bool(x) and bool(y) and (
        re.search(r'(^|\s)%s($|\s)' % re.escape(x), y) is not None)


def _same_name(a, b):
    """性能名对得上吗。一端包含另一端也算（`tensile strength` vs `ultimate tensile strength`）。"""
    x, y = _norm(a), _norm(b)
    if not x or not y:
        return False
    return x == y or x in y or y in x


def score_paper(gold_paper, rows):
    """一篇的打分。`rows` 是抽出来的记录（含 sample_id / name / value / unit）。"""
    single = bool(gold_paper.get('single_sample'))
    core = list(gold_paper.get('core') or [])
    edge = list(gold_paper.get('edge') or [])
    neg = list(gold_paper.get('negative') or [])
    rows = [r for r in (rows or []) if r.get('value') is not None]

    hit_core, mislabeled, unmatched = [], [], []
    used = set()
    for g in core:
        for i, r in enumerate(rows):
            if i in used or not _same_value(r.get('value'), g['value']):
                continue
            if not _same_sample(r.get('sample_id'), g['sample_id'], single):
                continue
            used.add(i)
            (hit_core if _same_name(r.get('name'), g['name']) else mislabeled).append(
                {'gold': g, 'got': r})
            break
        else:
            unmatched.append(g)

    hit_edge = 0
    for g in edge:
        for i, r in enumerate(rows):
            if i not in used and _same_value(r.get('value'), g['value']):
                used.add(i)
                hit_edge += 1
                break

    hard = []
    for g in neg:
        for i, r in enumerate(rows):
            if i not in used and _same_value(r.get('value'), g['value']):
                used.add(i)
                hard.append({'gold': g, 'got': r})
                break

    n_rows = len(rows)
    n_good = len(hit_core) + len(mislabeled) + hit_edge
    return {
        'key': gold_paper.get('key', ''),
        'n_rows': n_rows,
        'n_core': len(core),
        'recall': (len(hit_core) / len(core)) if core else None,
        'precision': (n_good / n_rows) if n_rows else None,
        'mislabel_rate': (len(mislabeled) / (len(hit_core) + len(mislabeled)))
                         if (hit_core or mislabeled) else None,
        'n_hard_errors': len(hard),
        'missed': [{'sample_id': g['sample_id'], 'name': g['name'],
                    'value': g['value'], 'unit': g.get('unit', '')} for g in unmatched],
        'mislabeled': [{'value': m['gold']['value'],
                        'gold_name': m['gold']['name'],
                        'got_name': m['got'].get('name')} for m in mislabeled],
        'hard_errors': [{'value': h['gold']['value'], 'why': h['gold']['why'],
                         'got_as': h['got'].get('name')} for h in hard],
    }


def format_report(scores):
    """给人看的一行一篇。**分数后面永远跟着漏了什么** —— 只有数字的报告没人会去修。"""
    out = []
    for s in scores:
        def pct(x):
            return '—' if x is None else '%.0f%%' % (x * 100)
        out.append('%s  召回 %s（%d/%d）｜准确 %s｜错标 %s｜硬错误 %d 条'
                   % (s['key'], pct(s['recall']),
                      round((s['recall'] or 0) * s['n_core']), s['n_core'],
                      pct(s['precision']), pct(s['mislabel_rate']), s['n_hard_errors']))
        for m in s['missed'][:6]:
            out.append('    漏：%s / %s = %s %s' % (m['sample_id'], m['name'],
                                                   m['value'], m['unit']))
        for m in s['mislabeled'][:6]:
            out.append('    错标：%s 应是 %r，抽成了 %r'
                       % (m['value'], m['gold_name'], m['got_name']))
        for h in s['hard_errors'][:6]:
            out.append('    硬错误：%s 被当成 %r —— %s'
                       % (h['value'], h['got_as'], h['why']))
    return '\n'.join(out)
