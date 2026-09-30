# -*- coding: utf-8 -*-
"""数值库的推导列与去重视图（2026-09-30，Claude Science 复测提的：建 ML 数据集的三个坑）。

① 同一个量两种单位写法（kJ/mol 与 kJ mol-1）→ unit_norm 统一
② 「提高 40%」与绝对值混在一起 → kind 分开（按性质该有的量纲判）
③ papers 表同一 DOI 两行（全文层 + 摘要层）→ 视图 papers_canonical 每个 DOI 只留最高档
"""
import sqlite3

import pytest

from tools import paperdb
from tools.paperdb import derive


@pytest.mark.parametrize('name,unit,kind', [
    ('tensile strength', 'MPa', 'absolute'),
    ('tensile strength', '%', 'relative'),          # 「拉伸强度提高 40%」
    ('impact strength', '%', 'relative'),
    ('impact strength', 'kJ/m2', 'absolute'),
    ('elongation at break', '%', 'absolute'),       # 本来就是无量纲，% 是绝对值
    ('tensile strength', 'mm', 'mismatch'),         # 量纲不对，抽错了
    ('%', '%', 'bad_name'),                         # 名字只是个单位
])
def test_相对还是绝对按性质该有的量纲判(name, unit, kind):
    assert derive({'name': name, 'unit': unit, 'value': 40})['kind'] == kind


def test_同一单位两种写法规范成一种():
    a = derive({'name': 'activation energy', 'unit': 'kJ mol-1', 'value': 80})
    b = derive({'name': 'activation energy', 'unit': 'kJ/mol', 'value': 80})
    assert a['unit_norm'] == b['unit_norm'] and a['value_si'] == b['value_si'] == 80000


def test_换到国际单位_摄氏度走仿射换算():
    d = derive({'name': 'glass transition temperature', 'unit': '°C', 'value': -20})
    assert abs(d['value_si'] - 253.15) < 1e-6 and d['si_unit'] == 'K'
    t = derive({'name': 'toughness', 'unit': 'MJ m-3', 'value': 5, 'value_max': 7})
    assert t['value_si'] == 5e6 and t['value_max_si'] == 7e6


def test_相对变化不换算():
    d = derive({'name': 'tensile strength', 'unit': '%', 'value': 40})
    assert d['value_si'] is None and d['si_unit'] == ''


def test_papers_canonical_每个DOI只留最高档():
    conn = sqlite3.connect(':memory:')
    conn.executescript(paperdb._DDL)
    cols = [r[1] for r in conn.execute('PRAGMA table_info(papers)')]
    def put(key, doi, tier):
        row = {c: None for c in cols}
        row.update(key=key, doi=doi, tier=tier)
        conn.execute('INSERT INTO papers (%s) VALUES (%s)' % (
            ','.join('"%s"' % c for c in cols), ','.join('?' * len(cols))), [row[c] for c in cols])
    put('FNSXGZVE', '10.1002/adfm.1', '粗层')
    put('W7124601603', '10.1002/ADFM.1', '摘要')
    put('ABCD1234', '10.1/x', '精+SI')
    put('NODOI001', '', '摘要')
    got = sorted(r[0] for r in conn.execute('SELECT key FROM papers_canonical'))
    assert got == ['ABCD1234', 'FNSXGZVE', 'NODOI001']
