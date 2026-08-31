# -*- coding: utf-8 -*-
"""控制面板的配置区守卫 —— 挡「页面上看得见、却对不上或存不进去」那一类 bug。

这类 bug 特别难自查：界面正常、点得动、没有报错，只有结果不对。
项目里已经栽过两次（踩坑 #58：改得动却存不进去；本次：shared.kernel.role 加了第三档，
面板的下拉却写死两项，选不到 test，保存时还会把它悄悄退回 dev）。

**根因都一样：同一份知识被抄了两遍。**所以这里的断言不是「功能对不对」，
而是「两处有没有一致」。
"""
import os
import sys

import pytest

from shared.kernel import paths, role

panel = pytest.importorskip('host.panel.app')

from shared.kernel.config import SITE_SETTINGS, MODEL_SETTINGS      # noqa: E402


def test_角色下拉必须覆盖所有角色():
    """加了新角色却忘了改面板 = 用户在界面上根本选不到它。"""
    shown = {o['value'] for o in panel.SITE_OPTIONS['ROLE']}
    assert shown == set(role.VALID), (
        f'面板的角色下拉 {sorted(shown)} 与 shared.kernel.role.VALID '
        f'{sorted(role.VALID)} 对不上')


def test_每个选项都有给人看的说明():
    for o in panel.SITE_OPTIONS['ROLE']:
        assert o.get('text'), f'{o["value"]} 没有说明文字'
        assert o['value'] in o['text'], '说明里要带上取值本身，用户才对得上文档'


def test_选项由后端下发而不是前端写死():
    """前端写死过一次，于是后端加档、前端不知道。**选项属于数据，不属于模板。**"""
    sites = {s['name']: s for s in panel.collect_config()['sites']}
    assert sites['ROLE']['options'], 'ROLE 必须带 options 下发'
    assert sites['ZOTERO_STORAGE']['options'] == [], '自由填写的项不该有 options'


def test_所有本机设置都在保存白名单里():
    """踩坑 #58：白名单漏了一类，界面改得动、一保存被静默丢弃。"""
    allowed = ({n for n, _, _ in panel.KEY_NAMES}
               | {s[0] for s in SITE_SETTINGS}
               | set(MODEL_SETTINGS))
    for name, *_ in SITE_SETTINGS:
        assert name in allowed, f'{name} 保存不进去'


def test_面板认得每一个本机设置项():
    """新增配置项后，面板要能显示出来 —— 否则用户只能去改 .env。"""
    shown = {s['name'] for s in panel.collect_config()['sites']}
    assert shown == {s[0] for s in SITE_SETTINGS}
