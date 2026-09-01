# -*- coding: utf-8 -*-
"""curate 评测的评分器：**纯函数**，拿到「实际判断」就能打分。

这块的判断全是「输入 → 一个确定的答案」，所以判分就是比对，没有模糊空间。
刻意不在这里调被测函数 —— 评分器只管「对不对」，不管「怎么算出来的」，
这样换实现的时候这份判分标准一个字都不用改。
"""


def score(name, why, expect, actual):
    """一条金标 → {passed, why}。"""
    if expect == actual:
        return {'passed': True, 'why': f'{name}：{actual!r}'}
    return {'passed': False,
            'why': f'{name}：应该是 {expect!r}，实际 {actual!r}  —— {why}'}


def score_sets(name, why, expect, actual):
    """按集合比对（顺序不属于契约）。expect/actual 都是 key 列表。"""
    want, got = set(expect or []), set(actual or [])
    if want == got:
        return {'passed': True, 'why': f'{name}：{sorted(got) or "空"}'}
    missing, extra = sorted(want - got), sorted(got - want)
    bits = []
    if missing:
        bits.append(f'漏了 {missing}')
    if extra:
        bits.append(f'多了 {extra}')
    return {'passed': False, 'why': f'{name}：' + '、'.join(bits) + f'  —— {why}'}


def summarize(results):
    total = len(results)
    passed = sum(1 for r in results if r['passed'])
    return {'total': total, 'passed': passed,
            'pass_rate': (passed / total) if total else 0.0,
            'failures': [r['why'] for r in results if not r['passed']]}
