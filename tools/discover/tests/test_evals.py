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


def test_语义整个不可用时不假装排序():
    """没有向量库时每篇 relevance 都是 None。原来给一律 0.5，排序只剩被引数 ——
    万引的通用综述全浮到顶上（2026-09-13 编程端实测，对题的排第 42）。
    退化时要按检索引擎给的顺序为主，并在 match 上标 rank_mode。"""
    papers = [{'title': 'on-topic 2026', 'year': 2026, 'citations': 3},
              {'title': 'on-topic 2025', 'year': 2025, 'citations': 10},
              {'title': 'generic review 2019', 'year': 2019, 'citations': 2599}]
    ms = [{'relevance': None, 'status': 'new'} for _ in papers]
    rows = match.rank(papers, ms, year_now=2026)
    assert [p['title'] for p, _m, _s in rows][0] == 'on-topic 2026', '检索顺序在前的该在前，不该被万引综述压下去'
    assert all(m.get('rank_mode') == 'no_semantic' for _p, m, _s in rows)


def test_只有个别篇算不出相关度时仍按原逻辑():
    papers = [{'title': 'a', 'year': 2025, 'citations': 0}, {'title': 'b', 'year': 2025, 'citations': 0}]
    ms = [{'relevance': 0.9, 'status': 'new'}, {'relevance': None, 'status': 'new'}]
    rows = match.rank(papers, ms, year_now=2026)
    assert rows[0][0]['title'] == 'a'
    assert not any(m.get('rank_mode') for _p, m, _s in rows)


def test_新方向模式不按近库度排():
    """用户找新方向时（2026-09-13），默认的 relevance=√(近库×贴题) 会把离库远的压下去 ——
    正好是反向拉力。explore=True 时只看贴题度；近库度留着当事实给人看。"""
    papers = [{'title': '离库远但正对题', 'year': 2025, 'citations': 5},
              {'title': '离库近但跑题',   'year': 2025, 'citations': 5}]
    ms = [{'relevance': 0.3, 'topic_sim': 0.9, 'lib_sim': 0.1, 'status': 'new'},
          {'relevance': 0.7, 'topic_sim': 0.5, 'lib_sim': 0.98, 'status': 'new'}]
    default = [p['title'] for p, _m, _s in match.rank(papers, ms, year_now=2026)]
    explore = [p['title'] for p, _m, _s in match.rank(papers, ms, year_now=2026, explore=True)]
    assert default[0] == '离库近但跑题', '默认模式确实会被库拖着走（这正是要给用户开关的理由）'
    assert explore[0] == '离库远但正对题', '新方向模式必须把它翻过来'


def test_新方向模式的雪球种子来自本次命中而非库():
    """2026-09-13 主力机实测：排序翻了、种子仍从库里挑，雪球带回的 130 多篇全在库的
    引用邻域里，前十名「离你的库」清一色是近 —— 候选池没翻等于没找新方向。"""
    from tools.discover import _seeds_from_hits
    hits = [{'doi': '10.1/a', 'title': 'A', 'citations': 3},
            {'title': '没 DOI 的不能当种子', 'citations': 999},
            {'doi': '10.1/b', 'title': 'B', 'citations': 40},
            {'doi': '10.1/c', 'title': 'C', 'citations': 12}]
    seeds = _seeds_from_hits(hits, 2)
    assert [s['doi'] for s in seeds] == ['10.1/b', '10.1/c'], '取本次命中里被引最多且有 DOI 的'
    assert all(s['sim'] is None for s in seeds), '不是按近库度挑的，就别给一个近库度'
