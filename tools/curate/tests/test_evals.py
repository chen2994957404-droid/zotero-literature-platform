# -*- coding: utf-8 -*-
"""跑 curate 的金标评测 —— 全离线、不碰真实 Zotero 库。

**为什么这块的评测优先级高于别的工具**：curate 做的是改附件名、删条目、改标签，
全是写用户真实库的**不可逆**操作。别的工具判错了重跑一次就行，这里判错了
用户得人工收拾。而这四个判断又全是纯函数，秒级可验 —— 没有理由不验。

金标在 `evals/golden/decisions.json`，加用例不用改这个文件。
"""
import pytest

from tools.curate import evals, junk, rename, tags
from tools.curate.evals.scorers import decisions as sc


@pytest.fixture(scope='module')
def g():
    return evals.golden()


def test_附件分类金标全过(g):
    """正文 / SI / 快照分不清，改名就会把它们的名字互相写错。"""
    results = [sc.score(c['name'], c['why'], c['expect'], rename.classify(c['in']))
               for c in g['classify']]
    s = sc.summarize(results)
    assert s['pass_rate'] >= evals.MIN_PASS_RATE, (
        f"{s['passed']}/{s['total']}：\n  " + '\n  '.join(s['failures']))


def test_垃圾条目分组金标全过(g):
    """A 组（重复残留，删了不丢东西）和 B 组（库里独一份，**删了就真没了**）
    的代价完全不同 —— 分错组是这个工具能犯的最贵的错。
    """
    results = []
    for c in g['split_junk']:
        A, B = junk.split_junk(c['tops'])
        results.append(sc.score_sets(c['name'] + ' · A组', c['why'], c['expect_A'],
                                     [x['data']['key'] for x in A]))
        results.append(sc.score_sets(c['name'] + ' · B组', c['why'], c['expect_B'],
                                     [x['data']['key'] for x in B]))
    s = sc.summarize(results)
    assert s['pass_rate'] >= evals.MIN_PASS_RATE, (
        f"{s['passed']}/{s['total']}：\n  " + '\n  '.join(s['failures']))


def test_标签改写金标全过(g):
    """返回 None 的语义是「这条不用写回 Zotero」——
    判错就是白打一次 API，全库跑一遍就是白撞一次限流（踩坑 #10）。
    """
    results = [sc.score(c['name'], c['why'], c['expect'], tags.nested_of(c['in']))
               for c in g['nested_of']]
    s = sc.summarize(results)
    assert s['pass_rate'] >= evals.MIN_PASS_RATE, (
        f"{s['passed']}/{s['total']}：\n  " + '\n  '.join(s['failures']))


def test_模型结果转标签金标全过(g):
    """模型偶尔会吐 null / 数字 / 大小写不一 —— 不过滤就是往用户库里写垃圾。"""
    results = [sc.score(c['name'], c['why'], c['expect'], tags.to_tags(c['in']))
               for c in g['to_tags']]
    s = sc.summarize(results)
    assert s['pass_rate'] >= evals.MIN_PASS_RATE, (
        f"{s['passed']}/{s['total']}：\n  " + '\n  '.join(s['failures']))


def test_每条金标都写了为什么要验它(g):
    """**说不清为什么要验，就说明这条不值得验。**"""
    bad = []
    for group, cases in g.items():
        if group.startswith('_'):
            continue
        bad += [f"{group}/{c.get('name', '?')}" for c in cases
                if len((c.get('why') or '').strip()) < 8]
    assert not bad, f'这些用例没写 why：{bad}'


def test_SI判据全项目只有一份():
    """宪法铁律 1。

    2026-09-01 之前有两份（`zotero_client.SUPP_PAT` 与 `curate.rename.SUPP`），
    而且**内容不一样** —— 同一个 `..._MOESM1_ESM.pdf`，精读线认得出是 SI，
    改名线把它当正文。这条钉住「合并之后别又分家」。
    """
    from shared.adapters import zotero_client
    assert rename.SUPP is zotero_client.SUPP_PAT, (
        'curate 又有了自己的一份 SI 判据 —— 两份迟早会不一致，'
        '而不一致的那一天，改名会把 SI 当正文写进用户的库')
