# -*- coding: utf-8 -*-
"""单元库：形状校验、稳定 id、去重、按生产者合并、原子落盘（2026-09-22）。全部离线。"""
import json
import io
import os

import pytest

from shared.kernel import paths, units_store
from shared.kernel import units_store as U


@pytest.fixture
def curated(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, 'CURATED', str(tmp_path / 'curated'))
    return tmp_path


def _fact(sample, prop, value, producer='fine_fact', **checks):
    return U.make_unit('fact', {'sample': sample, 'property': prop, 'value': value, 'unit': ''},
                       {'where': 'main', 'quote': 'the %s of %s was %s' % (prop, sample, value), 'pos': 0.1},
                       {'producer': producer, 'model': 'm', 'ver': 1}, checks)


def test_稳定id_与去重():
    a = _fact('FC-EtFe', 'tensile strength', '7.11 MPa')
    b = _fact(' fc-etfe', 'Tensile  Strength', '7.11 MPa', dimension_ok=True)
    assert a['id'] == b['id']
    kept = U.dedupe([a, b])
    assert len(kept) == 1 and kept[0]['checks'].get('dimension_ok') is True     # 证据多的那条留下


def test_形状校验_缺必填与无引用都拒():
    with pytest.raises(ValueError):
        U.make_unit('fact', {'value': '1'}, {'quote': 'q'}, {'producer': 'p'})
    with pytest.raises(ValueError):
        U.make_unit('claim', {'text': 'x'}, {'quote': ''}, {'producer': 'p'})
    u = _fact('S', 'toughness', '3 MJ m-3')
    u['fields']['bogus'] = 1
    assert any('未知字段' in p for p in U.validate(u))


def test_落盘_合并_按生产者替换(curated):
    key = 'ABCD1234'
    a, b = _fact('S1', 'tensile strength', '1 MPa'), _fact('S1', 'toughness', '2 MJ m-3')
    c = U.make_unit('claim', {'text': 'it is tough'}, {'quote': 'it is tough'}, {'producer': 'units_src', 'model': 'm', 'ver': 1})
    units_store.save(key, [a, b, c])
    assert os.path.exists(paths.units(key)) and not os.path.exists(paths.units(key) + '.tmp')
    d = json.load(io.open(paths.units(key), encoding='utf-8'))
    assert d['schema_ver'] == U.SCHEMA_VER and len(d['units']) == 3
    # 同生产者重抽：旧的 fact 全清掉，claim（别的生产者）留着
    a2 = _fact('S1', 'tensile strength', '1.5 MPa')
    merged = units_store.merge(key, [a2], producer='fine_fact')
    types = units_store.stats(merged)
    assert types == {'claim': 1, 'fact': 1} and merged[-1]['fields']['value'] == '1.5 MPa'


def test_没有文件时读到空(curated):
    assert units_store.load('ZZZZ9999') == []
