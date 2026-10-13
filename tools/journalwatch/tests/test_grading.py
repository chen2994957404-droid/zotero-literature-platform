# -*- coding: utf-8 -*-
"""期刊分级（tools.journalwatch.grading，2026-10-13 从 tools/curate 搬来）—— 档次判定是纯逻辑，离线可测。"""
from tools.journalwatch import grading as journals

TOP = {'display_name': 'Advanced Materials', 'host_organization_name': 'Wiley',
       'summary_stats': {'2yr_mean_citedness': 22.4}}
MID = {'display_name': 'Some Journal', 'summary_stats': {'2yr_mean_citedness': 9.1}}
LOW = {'display_name': 'Tiny Journal', 'summary_stats': {'2yr_mean_citedness': 1.2}}
UNKNOWN = {'display_name': 'No Metrics Journal'}
MDPI = {'display_name': 'Polymers', 'host_organization_name': 'Multidisciplinary Digital Publishing Institute',
        'summary_stats': {'2yr_mean_citedness': 7.3}}


def test_按近两年篇均被引分档_查不到指标算一般():
    assert [journals.tier_of(x)[0] for x in (TOP, MID, LOW, UNKNOWN)] == ['顶刊', '一流', '一般', '一般']


def test_用户名单压过指标():
    t, why = journals.tier_of(MDPI, journals.DEFAULT_OVERRIDES)
    assert t == '慎用' and '用户名单' in why
    assert journals.tier_of(MDPI)[0] == '常规'


def test_名单可以按刊名单点一本():
    ov = {'journals': {'tiny journal': '慎用'}}
    assert journals.tier_of(LOW, ov)[0] == '慎用' and journals.tier_of(TOP, ov)[0] == '顶刊'
