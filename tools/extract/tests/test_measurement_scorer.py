# -*- coding: utf-8 -*-
"""金标打分器的守卫：**这把尺子本身要先量得准**。

尺子错了比没有尺子更糟 —— 后面所有模型选型都会依据它。
"""
import io
import json
import os

from tools.extract.evals.scorers import measurements as M

GOLD = os.path.join(os.path.dirname(M.__file__), '..', 'golden', 'measurements.json')


def _gold(key):
    d = json.load(io.open(os.path.abspath(GOLD), encoding='utf-8'))
    return next(p for p in d['papers'] if p['key'] == key)


def test_金标文件本身是完整的():
    d = json.load(io.open(os.path.abspath(GOLD), encoding='utf-8'))
    assert len(d['papers']) == 3
    for p in d['papers']:
        assert p['core'] and p['negative'], p['key']
        for row in p['core']:
            assert row['value'] is not None and row['sample_id'] and row['name']
            assert row.get('quote'), '每条 core 都要带原文，否则用户没法抽查'


def test_全抽对就是满分():
    g = _gold('CL2HILJ9')
    rows = [{'sample_id': c['sample_id'], 'name': c['name'], 'value': c['value'],
             'unit': c.get('unit', '')} for c in g['core']]
    s = M.score_paper(g, rows)
    assert s['recall'] == 1.0 and s['precision'] == 1.0
    assert s['mislabel_rate'] == 0.0 and s['n_hard_errors'] == 0


def test_数值对但性能名错_算错标而不算抽对():
    """这是整把尺子最重要的一条：接地率对这种错完全失明。"""
    g = _gold('CL2HILJ9')
    s = M.score_paper(g, [{'sample_id': 'SPU/10D-SiO2', 'name': "young's modulus",
                           'value': 19.5, 'unit': 'MPa'}])
    assert s['mislabel_rate'] == 1.0
    assert s['recall'] == 0.0, '错标不能算召回'
    assert s['mislabeled'][0]['gold_name'] == 'tensile strength'


def test_抽了别人文献里的数_算硬错误():
    g = _gold('CL2HILJ9')
    s = M.score_paper(g, [{'sample_id': 'SPU', 'name': 'tensile strength',
                           'value': 73.6, 'unit': 'MPa'}])
    assert s['n_hard_errors'] == 1
    assert '别人文献' in s['hard_errors'][0]['why']


def test_样品挂错了不算抽对():
    """`PBS1 到 PBS6 是 243, 129, 73...` —— 数字容易，挂对样品难。"""
    g = _gold('VHJI4A32')
    s = M.score_paper(g, [{'sample_id': 'PBS2', 'name': 'plateau elastic modulus',
                           'value': 243, 'unit': 'kPa'}])
    assert s['recall'] == 0.0, '243 是 PBS1 的，挂到 PBS2 上不能算对'


def test_边界情况不加分也不扣分():
    g = _gold('P2Q5TYFR')
    s = M.score_paper(g, [{'sample_id': '2', 'name': 'yield', 'value': 93, 'unit': '%'}])
    assert s['recall'] == 0.0
    assert s['precision'] == 1.0, 'edge 抽到了不该算作错'
    assert s['n_hard_errors'] == 0


def test_1个百分点内的排版差异算同一个数():
    g = _gold('VHJI4A32')
    s = M.score_paper(g, [{'sample_id': 'PBS3', 'name': 'plateau elastic modulus',
                           'value': 73.0, 'unit': 'kPa'}])
    assert s['recall'] > 0


def test_漏抽要说清楚漏了哪几条():
    g = _gold('CL2HILJ9')
    s = M.score_paper(g, [])
    assert s['recall'] == 0.0 and len(s['missed']) == len(g['core'])
    assert '只有数字的报告没人会去修' or M.format_report([s])


def test_单体系论文里unknown是正确答案():
    """P2Q5TYFR 全篇一个聚合物，正文不指明样品是正常写法。"""
    g = _gold('P2Q5TYFR')
    assert g['single_sample'] is True
    s = M.score_paper(g, [{'sample_id': 'unknown', 'name': 'detection limit',
                           'value': 1e-10, 'unit': 'M'}])
    assert s['recall'] > 0, '单体系论文里 unknown 不该算漏抽'


def test_多体系论文里unknown照样不算对():
    """`PBS1 到 PBS6 是 243, 129...` —— 这里样品归属正是考点，不能放水。"""
    g = _gold('VHJI4A32')
    assert g['single_sample'] is False
    s = M.score_paper(g, [{'sample_id': 'unknown', 'name': 'plateau elastic modulus',
                           'value': 243, 'unit': 'kPa'}])
    assert s['recall'] == 0.0, '多体系论文里 unknown 不能算抽对'
