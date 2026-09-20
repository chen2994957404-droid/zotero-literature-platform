# -*- coding: utf-8 -*-
"""单元拆解研究：范文分栏、单元解析、原文定位（2026-09-20）。模型换成假替身，测的是编排。"""
from tools.deepread.evals import units as U
from tools.deepread.tests.test_sectioned import MD
from shared.domain.schema import outline as ol

REF = ('# T\n\n来源: x\n\n近期，A B 报道了一种弹性体，拉伸强度达 12.5 MPa。\n\n'
       '冲击防护需要速率依赖的材料，这是一段足够长的引言背景，讲了前人的工作只做到了三点二兆帕，并且说明了为什么这很重要，所以要继续写下去，一直写到超过六十个字为止。\n\n'
       '（1）主要实验药品是：PDMS 和硼酸。\n\nQuestion：各组分的作用是？🍁PDMS 提供骨架。\n\n'
       '图1，标题为"力学"。\n\n▲图1，模量为 4.1 MPa。\n\nQuestion：本论文中所制备的材料为何性能优异？☘️动态交换。\n\n'
       '总之，转化了问题。\n\n通俗理解：像橡皮泥。\n\n文献信息 DOI: x\n')


def test_范文按范式起笔分栏_文献信息丢掉():
    cols = [c for c, _ in U.paragraphs(REF)]
    assert cols == ['导读', '引言', '实验', 'Q1', '图', 'Q2', '总之', '通俗理解']


def test_单元解析_只认七类_带栏名():
    def fake(sysp, user, **kw):
        return {'units': [{'type': 'Fact', 'sample': 'PBS', 'property': 'modulus', 'value': '4.1', 'unit': 'MPa'},
                          {'type': 'nonsense', 'x': 1}]}
    us, bad = U.split_units(fake, '图', '▲图1，模量为 4.1 MPa。')
    assert not bad and len(us) == 1 and us[0]['type'] == 'fact' and us[0]['col'] == '图'


def test_定位_数值优先_落到骨架节类():
    o = ol.build_outline(MD)
    loc = U.locate({'type': 'fact', 'value': '4.1', 'unit': 'MPa'}, MD, o)
    assert loc['where'] == 'main' and loc['kind'] and 0 < loc['pos'] < 1
    assert U.locate({'type': 'claim', 'text': '很好'}, MD, o)['where'] == 'none'
    assert U.locate({'type': 'fact', 'value': '999'}, MD, o, si_md='SI says 999 kPa')['where'] == 'si'


def test_汇总_栏乘类矩阵():
    r = {'pid': 'X', 'n_paras': 2, 'ref_chars': 100, 'failed_paras': 0, 'has_si': False,
         'units': [{'type': 'fact', 'col': '图', 'len': 30, 'loc': {'where': 'main', 'kind': '结果', 'pos': 0.5}},
                   {'type': 'claim', 'col': '总之', 'len': 40, 'loc': {'where': 'none', 'kind': '', 'pos': None}}]}
    s = U.summarize([r])
    assert s['col_type']['图']['fact'] == 1 and s['by_type']['claim']['none'] == 1
    assert s['per_paper'][0]['total'] == 2


def test_老版式_头部DOI行不把整篇吞成文献信息():
    ref = '# T\n\n来源: x\nDOI: 10.1/x\n\n---\n\nJessica 高分子学人\n\n东华大学团队聚焦于水下粘合剂难题，合成含氟离子液体基粘合剂，形成坚固疏水网络，这是一段足够长的正文。\n\n1. 1\n\n引言\n\n水下粘合在多个领域发挥重要作用。\n'
    ps = U.paragraphs(ref)
    assert ps and all(c != '文献信息' for c, _ in ps) and '水下粘合' in ''.join(t for _, t in ps)
