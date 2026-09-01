# -*- coding: utf-8 -*-
"""extract 评测的评分器：**纯函数**。

性能拆解的比对刻意只看**关心的那几个键**（name/value/value_max/unit/cmp），
不整字典相等 —— 以后给 `parse_properties` 加个 `raw` 之类的新键，
不该让整套金标变红。**评测红了却不代表出问题，是评测失效的第一步。**
"""

_KEYS = ('name', 'value', 'value_max', 'unit', 'cmp')


def score(case, actual):
    name, why = case.get('name', '?'), case.get('why', '')
    if actual == case.get('expect'):
        return {'passed': True, 'why': f'{name}：{actual!r}'}
    return {'passed': False,
            'why': f'{name}：应该是 {case.get("expect")!r}，实际 {actual!r}  —— {why}'}


def score_props(case, actual_props):
    """只比关心的那几个键，且按顺序（一行里的多条本来就有先后）。"""
    name, why = case.get('name', '?'), case.get('why', '')
    got = [{k: p.get(k) for k in _KEYS} for p in actual_props]
    want = [{k: p.get(k) for k in _KEYS} for p in case['expect']]
    if got == want:
        return {'passed': True, 'why': f'{name}：拆出 {len(got)} 条'}
    return {'passed': False, 'why': f'{name}：应该是 {want}，实际 {got}  —— {why}'}


def summarize(results):
    total = len(results)
    passed = sum(1 for r in results if r['passed'])
    return {'total': total, 'passed': passed,
            'pass_rate': (passed / total) if total else 0.0,
            'failures': [r['why'] for r in results if not r['passed']]}
