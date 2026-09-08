# -*- coding: utf-8 -*-
"""小模型「装错盒子」时，脚本要认回来（2026-09-08 实测驱动）。

背景：`gemma3:1b` 跑一篇 13 段，34 条被判「没有数值」。逐条看下来
**模型认对了东西、填错了格子** —— 值写进 name、性能名写进 value_text。
判断（这个数是不是性能）是模型的活，装箱是脚本的活。这组测试钉的就是这个分工。

⚠ 认盒子**不许放宽接地校验**：数字仍然必须在这段原文里逐字找得到。
"""
from tools.extract.chunk_pass import validate

CHUNK = ('The PUU-3 sample shows a tensile strength of 43.1 MPa and an elongation '
         'at break of 600% (Table 2). Toughness reached 2059 kJ m-2. '
         'A PUU sheet of 2.0 g was used for each test.')
SAMPLES = ['PUU']          # 名单只有表格里那个写法，正文里还有 PUU-3


def _one(rows):
    return validate(rows, CHUNK, SAMPLES)


def test_值填进了性能名那格_也要认回来():
    kept, drop = _one([{'sample_id': 'PUU', 'name': '43.1 MPa', 'value_text': ''}])
    assert len(kept) == 1, f'没认回来：{drop}'
    assert kept[0]['value'] == 43.1 and kept[0]['unit'] == 'MPa'


def test_性能名与值互换_也要认回来():
    kept, _ = _one([{'sample_id': 'PUU', 'name': '43.1 MPa',
                     'value_text': 'tensile strength'}])
    assert len(kept) == 1
    assert kept[0]['value'] == 43.1
    assert 'tensile' in kept[0]['name'], kept[0]['name']


def test_名单外的样品名_只要原文里有就不算编的():
    """名单来自表格（`PUU`），正文写的是 `PUU-3` —— 模型照抄原文反而被判编造。"""
    kept, drop = _one([{'sample_id': 'PUU-3', 'name': 'tensile strength',
                        'value_text': '43.1 MPa'}])
    assert len(kept) == 1, f'照抄原文的样品名被判成编的：{drop}'
    assert kept[0]['sample_id'] == 'PUU-3'


def test_原文里没有的样品名_照样判掉():
    kept, drop = _one([{'sample_id': 'PVA-9', 'name': 'tensile strength',
                        'value_text': '43.1 MPa'}])
    assert not kept and drop['编的样品'] == 1


def test_投料量单独归类_不再冒充编样品():
    """`2.0 g 的 PUU sheet` 是配方，不是性能。丢，但要丢得有名有姓。"""
    kept, drop = _one([{'sample_id': 'PUU-1', 'name': 'PUU sheet',
                        'value_text': '2.0 g'}])
    assert not kept and drop['配方投料量'] == 1, drop


def test_编的数字仍然一律丢掉():
    """认盒子不是放水：这段里没有 99.9，怎么装都不能留。"""
    kept, drop = _one([{'sample_id': 'PUU', 'name': '99.9 MPa', 'value_text': ''},
                       {'sample_id': 'PUU', 'name': 'tensile strength',
                        'value_text': '99.9 MPa'}])
    assert not kept and drop['编的数字'] == 2, drop


def test_三个格子全是废话_不猜():
    kept, drop = _one([{'sample_id': 'unknown', 'name': 'PUU',
                        'value_text': 'tensile strength'}])
    assert not kept and drop['没有数值'] == 1, drop
