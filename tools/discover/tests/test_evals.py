# -*- coding: utf-8 -*-
"""跑 discover 的金标评测 —— 全离线、不联网。

守的是踩坑 #38：**雪球一开就被高被引通用文献带偏**。解药是 `rank()` 的默认权重
（相关度压过被引，被引还开了方压缩）。不钉住的话，以后有人顺手调一下权重，
找文献就退化成「按被引排序」—— 而且**不会报错**，只会慢慢变得没用。

金标在 `evals/golden/ranking.json`，加用例不用改这个文件。
"""
import pytest

from tools.discover import evals, match
from tools.discover.evals.scorers import ordering as sc


@pytest.fixture(scope='module')
def g():
    return evals.golden()


def test_排序金标全过(g):
    results = []
    for case in g['rank']:
        papers = [dict(p, title=p['id']) for p in case['papers']]
        rows = match.rank(papers, case['matches'], year_now=case.get('year_now'))
        results.append(sc.score_order(case, [p['id'] for p, _m, _s in rows]))
    s = sc.summarize(results)
    assert s['pass_rate'] >= evals.MIN_PASS_RATE, (
        f"{s['passed']}/{s['total']}：\n  " + '\n  '.join(s['failures']))


def test_标题归一金标全过(g):
    results = [sc.score_value(c, match.norm_title(c['in'])) for c in g['norm_title']]
    s = sc.summarize(results)
    assert s['pass_rate'] >= evals.MIN_PASS_RATE, (
        f"{s['passed']}/{s['total']}：\n  " + '\n  '.join(s['failures']))


def test_重合度金标全过(g):
    results = [sc.score_range(c, match._overlap(c['a'], c['b'])) for c in g['overlap']]
    s = sc.summarize(results)
    assert s['pass_rate'] >= evals.MIN_PASS_RATE, (
        f"{s['passed']}/{s['total']}：\n  " + '\n  '.join(s['failures']))


def test_相关度权重仍然是大头():
    """把「相关度压过被引」这件事**从默认参数上**钉死，不只是从结果上。

    上面那些用例验的是「在当前权重下排序对不对」。这一条验的是权重本身 ——
    有人把 `w_cite` 调到 0.6 时，它会当场红，而不是等到某个用例恰好翻盘才红。
    """
    import inspect
    d = inspect.signature(match.rank).parameters
    w_rel = d['w_rel'].default
    w_cite = d['w_cite'].default
    w_fresh = d['w_fresh'].default
    assert w_rel > w_cite + w_fresh, (
        f'相关度权重 {w_rel} 不再压过「被引 {w_cite} + 新鲜度 {w_fresh}」之和 —— '
        '这个工具就退化成按热度排序了（踩坑 #38）')


def test_每条金标都写了为什么要验它(g):
    """**说不清为什么要验，就说明这条不值得验。**"""
    bad = []
    for group, cases in g.items():
        if group.startswith('_'):
            continue
        bad += [f"{group}/{c.get('name', '?')}" for c in cases
                if len((c.get('why') or '').strip()) < 8]
    assert not bad, f'这些用例没写 why：{bad}'
