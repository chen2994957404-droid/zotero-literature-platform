# -*- coding: utf-8 -*-
"""跑 direction 的金标评测 —— 全离线、不联网。

金标的答案**由构造保证**：造图时就规定好了哪几篇该是一簇，
不需要人工标注。见 `evals/__init__.py` 里的说明。

金标在 `evals/golden/clusters.json`，加用例不用改这个文件。
"""
import pytest

from tools.direction import bibliometrics as bib
from tools.direction import evals
from tools.direction.evals.scorers import grouping as sc


@pytest.fixture(scope='module')
def g():
    return evals.golden()


def _cluster(refsets):
    """一份 {论文: 引用集合} → 聚出来的簇（列表的列表）。"""
    sets = {k: set(v) for k, v in refsets.items()}
    keys, S = bib.coupling_matrix(sets)
    labels = bib.louvain(S, resolution=1.0, seed=0)
    return bib.groups_of(keys, labels, min_size=1)


def _check(results):
    s = sc.summarize(results)
    assert s['pass_rate'] >= evals.MIN_PASS_RATE, (
        f"{s['passed']}/{s['total']}：\n  " + '\n  '.join(s['failures']))


def test_聚类金标全过(g):
    """分不开意味着方向地图会把毫不相干的两支画成一支 ——
    用户看到的「这个方向的主流分支」就是假的，而且看不出来是假的。
    """
    _check([sc.score_groups(c, _cluster(c['refsets'])) for c in g['clustering']])


def test_相似度金标全过(g):
    """聚类只是下游。**相似度算错了，后面所有事都错**。"""
    results = []
    for c in g['similarity']:
        sets = {k: set(v) for k, v in c['refsets'].items()}
        keys, S = bib.coupling_matrix(sets)
        idx = {k: i for i, k in enumerate(keys)}
        same = float(S[idx[c['same_pair'][0]]][idx[c['same_pair'][1]]])
        diff = float(S[idx[c['diff_pair'][0]]][idx[c['diff_pair'][1]]])
        results.append(sc.score_gap(c, same, diff))
    _check(results)


def test_时间分桶金标全过(g):
    """方向地图的「这一支在升还是在降」全靠分桶。分错桶趋势就是假的。"""
    _check([sc.score_value(c, bib.half_year(c['date'])) for c in g['trend']])


def test_升降判定金标全过(g):
    """「这一支在快速升温」是给用户看的结论 —— 判据得稳定。"""
    _check([sc.score_value(c, bib.direction(c['counts'])) for c in g['direction_call']])


def test_簇的编号不属于契约():
    """社区发现给簇编的号是任意的（实测这次是 0 和 3，不是 0 和 1）。

    把编号判进去等于在验一个不存在的契约 —— 换个 seed 或改个实现就会红，
    而那种红不代表出问题。评分器按「集合的集合」比对，这条钉住它。
    """
    assert sc.score_groups({'name': 'x', 'expect_groups': [['a', 'b'], ['c']]},
                           [['c'], ['b', 'a']])['passed']
    assert not sc.score_groups({'name': 'x', 'expect_groups': [['a', 'b'], ['c']]},
                               [['a', 'b', 'c']])['passed']


def test_每条金标都写了为什么要验它(g):
    """**说不清为什么要验，就说明这条不值得验。**"""
    bad = []
    for group, cases in g.items():
        if group.startswith('_'):
            continue
        bad += [f"{group}/{c.get('name', '?')}" for c in cases
                if len((c.get('why') or '').strip()) < 8]
    assert not bad, f'这些用例没写 why：{bad}'
