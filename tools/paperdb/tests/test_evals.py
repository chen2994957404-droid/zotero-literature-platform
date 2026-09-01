# -*- coding: utf-8 -*-
"""跑 paperdb 的金标评测。

**评测和体检回答的是两个问题**：体检问「能不能跑」，评测问「跑出来的对不对」。
这一套全是确定性查询（造出来的记录 + 固定 SQL），所以它可以默认就跑 ——
不花钱、不联网、秒级。

金标在 `evals/golden/queries.json`，加用例不用改这个文件。
"""
import json
import os

import pytest

from tools import paperdb
from tools.paperdb import evals
from tools.paperdb.evals.scorers import query_match


@pytest.fixture
def db(tmp_path, monkeypatch):
    """把库和源 JSON 都指到 tmp_path —— **绝不碰用户真实数据**。"""
    from shared.kernel import paths
    st = tmp_path / 'structured'
    st.mkdir()
    monkeypatch.setattr(paths, 'STRUCTURED', str(st))
    monkeypatch.setattr(paperdb, 'db_path', lambda: str(tmp_path / 'papers.db'))
    paperdb.close()

    records, cases = evals.golden()
    for r in records:
        with open(st / f"{r['key']}.json", 'w', encoding='utf-8') as f:
            json.dump(r, f, ensure_ascii=False)
    paperdb.rebuild(log=lambda *_: None)
    yield cases
    paperdb.close()


def _run(case):
    """跑一条用例 → (实际 key 列表, 异常)。异常照原样带回去给评分器判。"""
    call = case['call']
    fn, args = call['fn'], dict(call.get('args') or {})
    try:
        if fn == 'query':
            rows = paperdb.query(args.pop('sql'), tuple(args.get('params') or ()))
        elif fn == 'find':
            rows = paperdb.find(**args)
        else:
            raise ValueError(f'金标里写了不认识的入口：{fn}')
    except Exception as e:                      # noqa: BLE001 —— 期望报错的用例要靠它
        return None, e
    return [r['key'] for r in rows], None


def test_金标评测全过(db):
    """通过率必须达到 `thresholds.toml` 里的阈值（现在是 1.0，一条都不许挂）。"""
    results = []
    for case in db:
        keys, err = _run(case)
        results.append(query_match.score_case(case, keys, err))

    s = query_match.summarize(results)
    assert s['pass_rate'] >= evals.MIN_PASS_RATE, (
        f"通过率 {s['passed']}/{s['total']}，低于阈值 {evals.MIN_PASS_RATE}：\n  "
        + '\n  '.join(s['failures']))


def test_每条金标都写了为什么要验它():
    """**说不清为什么要验，就说明这条不值得验。**

    没有这一条，金标会慢慢变成一堆没人敢删、也没人说得清的断言。
    """
    _records, cases = evals.golden()
    bad = [c.get('name', '?') for c in cases if len((c.get('why') or '').strip()) < 8]
    assert not bad, f'这些用例没写 why：{bad}'


def test_评分器不判顺序():
    """顺序不属于查询契约（`find()` 的排序会随档次规则调整）。

    把顺序判进去，一次无害的排序改动就会让整套评测变红 ——
    **评测红了却不代表出问题，是评测失效的第一步。**
    """
    case = {'name': 'x', 'expect_keys': ['A', 'B']}
    assert query_match.score_case(case, ['B', 'A'])['passed']
    assert not query_match.score_case(case, ['A'])['passed']
    assert not query_match.score_case(case, ['A', 'B', 'C'])['passed']


def test_期望报错的用例_真查通了要算失败():
    """闸门测试最容易写反：不报错反而应该算挂。"""
    case = {'name': '只读闸门', 'expect_error': True}
    assert not query_match.score_case(case, ['A'], None)['passed']
    assert query_match.score_case(case, None, ValueError('nope'))['passed']
