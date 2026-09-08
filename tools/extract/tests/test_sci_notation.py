# -*- coding: utf-8 -*-
"""科学计数法必须读对 —— 读错不报错，只是**错十个数量级**（2026-09-08）。

金标查出来的：`10^-10 M` 被读成 `10 M`。检出限 1e-10 变成 10，
而它在库里长得跟真数据一模一样，还会被拿去比大小、排名次。
"""
import pytest

from shared.domain import schema


@pytest.mark.parametrize('text, value, unit', [
    ('detection limit: 10^-10 M', 1e-10, 'M'),          # 光杆幂次（系数省略）
    ('viscosity: 1.2 x 10^4 Pa s', 12000.0, 'Pa s'),    # 带系数
    ('Mn: 4 × 10^4 g/mol', 40000.0, 'g/mol'),           # 全角乘号
    ('tensile strength: 12 MPa', 12.0, 'MPa'),          # 普通数别被动
    ('modulus: 210 kPa', 210.0, 'kPa'),                 # 含 10 的数别被误伤
])
def test_各种写法都读成同一个数(text, value, unit):
    r = schema.parse_property(text)
    assert r['value'] == pytest.approx(value), r
    assert r['unit'] == unit, r


def test_两种写法互相不踩():
    """先补光杆再补带系数的话，`1.2 x 10^4` 会变成 `1.2 x 1×10^4`，值读成 1.2。"""
    assert schema.parse_property('a: 1.2 x 10^4 Pa')['value'] == 12000.0


def test_不是幂次的10不受影响():
    assert schema.parse_property('ref 10')['value'] is None
    assert schema.parse_property('time: 10 h')['value'] == 10.0
