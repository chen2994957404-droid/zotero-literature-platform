# -*- coding: utf-8 -*-
"""discover 评测的评分器：**纯函数**，只管「排出来的顺序对不对」。

为什么判顺序而不判分数：分数是中间量，调一次权重它就全变了；
用户真正看见的是「哪几篇排在最前面」。钉分数会让一次无害的调权变红 ——
**评测红了却不代表出问题，是评测失效的第一步。**
"""


def score_order(case, actual_ids):
    name, why = case.get('name', '?'), case.get('why', '')
    want = case.get('expect_order') or []
    if list(actual_ids) == want:
        return {'passed': True, 'why': f'{name}：{actual_ids}'}
    return {'passed': False,
            'why': f'{name}：应该排成 {want}，实际 {list(actual_ids)}  —— {why}'}


def score_value(case, actual):
    name, why = case.get('name', '?'), case.get('why', '')
    if actual == case.get('expect'):
        return {'passed': True, 'why': f'{name}：{actual!r}'}
    return {'passed': False,
            'why': f'{name}：应该是 {case.get("expect")!r}，实际 {actual!r}  —— {why}'}


def score_range(case, actual):
    """落在 [min, max] 区间内就算过（相似度这种数不该钉死一个值）。"""
    name, why = case.get('name', '?'), case.get('why', '')
    lo, hi = case['min'], case['max']
    if lo <= actual <= hi:
        return {'passed': True, 'why': f'{name}：{actual:.3f}'}
    return {'passed': False,
            'why': f'{name}：应该在 [{lo}, {hi}]，实际 {actual:.3f}  —— {why}'}


def summarize(results):
    total = len(results)
    passed = sum(1 for r in results if r['passed'])
    return {'total': total, 'passed': passed,
            'pass_rate': (passed / total) if total else 0.0,
            'failures': [r['why'] for r in results if not r['passed']]}
