# -*- coding: utf-8 -*-
"""跑 extract 的金标评测 —— 全离线、不花钱。

验的是抽完之后那套**确定性的理解**（是不是综述、哪一档、哪些算有值、
性能怎么拆成数），不是「模型抽得准不准」—— 后者要人工核对过的真实记录当金标，
见 `evals/README.md`。

为什么这一半也值得验：**对比表和查询库的正确性全建在它们上面。**
档次判错，用户就分不清空格是「本来就没有」还是「粗层没抽到」，
对比表的价值当场归零。

金标在 `evals/golden/records.json`，加用例不用改这个文件。
"""
import pytest

from shared.domain import schema
from tools.extract import evals
from tools.extract.evals.scorers import records as sc


@pytest.fixture(scope='module')
def g():
    return evals.golden()


def _check(results):
    s = sc.summarize(results)
    assert s['pass_rate'] >= evals.MIN_PASS_RATE, (
        f"{s['passed']}/{s['total']}：\n  " + '\n  '.join(s['failures']))


def test_综述判定金标全过(g):
    """综述没有单一体系的数值，混进数值对比表只会污染它。"""
    _check([sc.score(c, schema.is_review(c['in'])) for c in g['is_review']])


def test_档次判定金标全过(g):
    """**料和模型是两件事**：`本地+SI` 的料和 `精+SI` 一样好，差的只是模型。
    分不开就不知道「这一格该不该花钱升级」。
    """
    _check([sc.score(c, schema.tier_label(c['in'])) for c in g['tier_label']])


def test_有值判定金标全过(g):
    """有值率是「要不要花钱重抽」的依据 —— 判错就是让用户按假数做决定。"""
    _check([sc.score(c, schema.has_value(c['in'])) for c in g['has_value']])


def test_性能拆解金标全过(g):
    """把 'tensile strength: 12 MPa' 拆成能比大小的数，是查询库存在的全部理由。"""
    _check([sc.score_props(c, schema.parse_properties(
        {'key': 'K', 'key_properties': c['in']})) for c in g['parse_properties']])


def test_有值率统计口径和查询库是同一个():
    """`schema.coverage` 必须是「各档次×各字段有值率」的**唯一**实现。

    2026-08-31 之前 `extract` 的重抽向导问的是 `paperdb.stats()`（工具调工具）。
    改成两边都调这个函数 —— 不是各写一遍，是同一个。
    两份实现迟早会不一致，而不一致的那天，用户会看到两个都自称正确的有值率。
    """
    recs = [{'key': 'A', 'source': 'fine', 'material_system': 'x', 'key_properties': 'N/A'},
            {'key': 'B', 'source': 'coarse', 'material_system': '', 'key_properties': '12 MPa'}]
    cov = schema.coverage(recs, ['material_system', 'key_properties'])
    assert set(cov) == {'精层', '粗层'}, f'档次没分开：{list(cov)}'
    assert cov['精层']['rate']['material_system'] == 1.0, '精层那条的体系字段有值，却没算进去'
    assert cov['粗层']['rate']['material_system'] == 0.0, '空串被当成了有值'
    assert cov['精层']['rate']['key_properties'] == 0.0, "'N/A' 被当成了有值"
    assert cov['精层']['n'] == 1 and cov['粗层']['n'] == 1, '篇数统计错了'


def test_每条金标都写了为什么要验它(g):
    """**说不清为什么要验，就说明这条不值得验。**"""
    bad = []
    for group, cases in g.items():
        if group.startswith('_'):
            continue
        bad += [f"{group}/{c.get('name', '?')}" for c in cases
                if len((c.get('why') or '').strip()) < 8]
    assert not bad, f'这些用例没写 why：{bad}'
