# -*- coding: utf-8 -*-
"""paperdb 评测的评分器：**纯函数**，拿到「实际返回」就能打分。

刻意做成纯函数（不建库、不查库、不碰文件）——这样它自己可以被毫秒级地测，
而且换掉底层存储（sqlite → 别的）时这份判分标准一个字都不用改。

判分方式是**集合比对**，不是逐行比对：查询的语义是「哪些篇符合」，
返回顺序不属于契约（`find()` 的排序会随 tier 规则调整）。
把顺序也判进去，会让一次无害的排序改动导致整套评测变红 ——
**评测红了却不代表出问题，是评测失效的第一步。**
"""


def score_case(case, actual_keys=None, error=None):
    """一条金标 → {passed, why}。

      case          金标里的一条（含 expect_keys 或 expect_error）
      actual_keys   实际返回的 key 列表；期望报错的用例传 None
      error         实际抛出的异常（没有就是 None）
    """
    name = case.get('name', '?')
    if case.get('expect_error'):
        if error is None:
            return {'passed': False,
                    'why': f'{name}：期望被拒绝，实际却查成功了（闸门没起作用）'}
        return {'passed': True, 'why': f'{name}：被正确拒绝'}

    if error is not None:
        return {'passed': False, 'why': f'{name}：不该报错却报了 —— {error}'}

    want = set(case.get('expect_keys') or [])
    got = set(actual_keys or [])
    if want == got:
        return {'passed': True, 'why': f'{name}：命中 {sorted(got) or "空"}'}
    missing, extra = sorted(want - got), sorted(got - want)
    bits = []
    if missing:
        bits.append(f'漏了 {missing}')
    if extra:
        bits.append(f'多了 {extra}')
    return {'passed': False, 'why': f'{name}：' + '、'.join(bits)}


def summarize(results):
    """一组打分 → {total, passed, pass_rate, failures}。"""
    total = len(results)
    passed = sum(1 for r in results if r['passed'])
    return {
        'total': total,
        'passed': passed,
        'pass_rate': (passed / total) if total else 0.0,
        'failures': [r['why'] for r in results if not r['passed']],
    }
