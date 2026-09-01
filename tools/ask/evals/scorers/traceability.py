# -*- coding: utf-8 -*-
"""ask / askworld 评测的评分器：**可追溯性**。

这两个工具的全部价值就是「答案带得出出处」。答案本身好不好要人读，
但**「每个片段都带着来源进上下文」「来源列表不撒谎」「没证据时不硬答」**
这三件事是纯结构问题，可以离线钉死。

判据刻意只看结构，不看模型说了什么 —— 模型输出每次都不一样，
拿它当金标的话评测会随机变红，而**随机变红的评测等于没有评测**。
"""
import re


def check_context(ctx, n_chunks):
    """上下文里每一段都要带出处标记。返回 (通过?, 说明)。"""
    marks = re.findall(r'【片段\s*(\d+)', ctx)
    if len(marks) != n_chunks:
        return False, f'{n_chunks} 段材料，只有 {len(marks)} 段带了出处标记'
    if sorted(int(m) for m in marks) != list(range(1, n_chunks + 1)):
        return False, f'片段编号不连续：{marks}'
    return True, f'{n_chunks} 段都带了出处'


def check_sources(sources, expect_titles):
    """来源列表必须**正好**是喂进去的那些（不多不少）。

    多了 = 凭空多出一篇没被引用的来源，用户会去翻一篇根本没参与作答的文献；
    少了 = 用户不知道这句话是从哪来的 —— 而那正是这个工具唯一的卖点。
    """
    got = {(s.get('title') or '')[:50] for s in sources}
    want = {t[:50] for t in expect_titles}
    if got == want:
        return True, f'{len(got)} 条来源，正好对上'
    return False, f'来源对不上：多了 {sorted(got - want)}，少了 {sorted(want - got)}'


def summarize(results):
    total = len(results)
    passed = sum(1 for r in results if r['passed'])
    return {'total': total, 'passed': passed,
            'pass_rate': (passed / total) if total else 0.0,
            'failures': [r['why'] for r in results if not r['passed']]}
