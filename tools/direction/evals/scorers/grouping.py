# -*- coding: utf-8 -*-
"""direction 评测的评分器：**纯函数**，比对「聚类结果」与「构造时就知道的答案」。

比对方式是**集合的集合**：簇之间没有顺序，簇内也没有顺序 ——
社区发现给簇编的号是任意的，把编号也判进去等于在验一个不存在的契约。
"""


def _canon(groups):
    """[[a,b],[c]] → {frozenset({a,b}), frozenset({c})}，消掉两层顺序。"""
    return {frozenset(g) for g in groups if g}


def score_groups(case, actual_groups):
    name, why = case.get('name', '?'), case.get('why', '')
    want, got = _canon(case['expect_groups']), _canon(actual_groups)
    if want == got:
        return {'passed': True, 'why': f'{name}：{[sorted(g) for g in got]}'}
    return {'passed': False,
            'why': (f'{name}：应该分成 {[sorted(g) for g in want]}，'
                    f'实际 {[sorted(g) for g in got]}  —— {why}')}


def score_gap(case, same, diff):
    """同簇相似度要比跨簇高出至少 min_gap。"""
    name, why = case.get('name', '?'), case.get('why', '')
    gap = same - diff
    if gap >= case['min_gap']:
        return {'passed': True, 'why': f'{name}：同簇 {same:.3f} vs 跨簇 {diff:.3f}'}
    return {'passed': False,
            'why': (f'{name}：同簇 {same:.3f} 只比跨簇 {diff:.3f} 高 {gap:.3f}，'
                    f'不足 {case["min_gap"]}  —— {why}')}


def score_value(case, actual, key='expect'):
    name, why = case.get('name', '?'), case.get('why', '')
    if actual == case.get(key):
        return {'passed': True, 'why': f'{name}：{actual!r}'}
    return {'passed': False,
            'why': f'{name}：应该是 {case.get(key)!r}，实际 {actual!r}  —— {why}'}


def summarize(results):
    total = len(results)
    passed = sum(1 for r in results if r['passed'])
    return {'total': total, 'passed': passed,
            'pass_rate': (passed / total) if total else 0.0,
            'failures': [r['why'] for r in results if not r['passed']]}
