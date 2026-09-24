# -*- coding: utf-8 -*-
"""找数（2026-09-24）：范文数有四分之一在原文里却没进候选 —— 公式写法、并列同单位、µ/μ、单位表外的写法。

实测来源：主力机 10 篇范文 115 个数，29 个在原文里但没进候选（docs/变更记录.md 2026-09-24）。
"""
from shared.domain.schema import scan
from tools.extract import fine_fact as F


def _found(tex):
    c = scan.clean_body(tex)
    f = scan.scan_numbers(c)
    return c, f, [n['raw'] for n in f] + [n['raw'] for n in F.pint_candidates(c, f)]


def test_希腊μ也认_公式里的波浪号不留():
    c, f, raws = _found(r'the diameters decreased from $876 \pm 154~\mu \mathrm{m}$ at')
    assert '876 μm' in raws and '154' not in ' '.join(raws), (c, raws)


def test_并列同单位_前面的数继承单位():
    _, _, raws = _found(r'The $E_{a}$ was $110.7\pm12.7$ and $103.3\pm1.7$ kJ mol $^{-1}$ for CAN')
    assert '110.7 kJ mol-1' in raws and '103.3 kJ mol-1' in raws
    _, _, raws = _found(r'which was 14.8 and 423.7 times that of FC-Et')
    assert '14.8 times' in raws
    _, _, raws = _found(r'between $75^{\circ}$ and $90^{\circ}$ C (Fig. 4')
    assert any(r.startswith('75') for r in raws)


def test_单位上的正幂次保留():
    c, _, raws = _found(r'a toughness of 58.9 MJ/m $^{3}$ , which')
    assert 'MJ/m3' in c and '58.9 MJ/m3' in raws


def test_无量纲_from_to_与_up_to():
    _, _, raws = _found('the Hermans orientation factor rose from 0.005 to 0.330 (Figure 5e)')
    assert '0.005' in raws and '0.330' in raws
    _, _, raws = _found('the healing efficiency rose from 0.42 to 0.83 after')
    assert '0.42' in raws and '0.83' in raws


def test_单位表外的写法交给Pint():
    _, _, raws = _found(r'a fracture energy as high as 283.6 MJ m $^{-2}$ (Figure 4i)')
    assert any(r.startswith('283.6 MJ') for r in raws)
    _, _, raws = _found(r'collagen content is about $0.87~\mu \mathrm{g} / \mathrm{mm}^2$ for uncoated')
    assert any(r.startswith('0.87 μg') for r in raws)


def test_编号与英文小词不当单位():
    _, _, raws = _found('as shown in Fig. 4 C and Table 2 in 2020, see ref. 25 in a dark room')
    assert raws == [], raws
    _, _, raws = _found('| PBS-1 | 3 in |')
    assert raws == [], '表格行归 scan_tables 管'


# ── 样品归属的三类错（2026-09-24）────────────────────────────────

def test_对照样_数在比较词前面就不归它():
    s = 'The FC-EtFe reached a toughness of 58.9 MJ/m3, which was 14.8 and 423.7 times that of FC-Et and FC-1T.'
    cands = ['FC-EtFe', 'FC-Et', 'FC-1T']
    assert F.fix_comparator(s, '423.7 times', 'FC-1T', cands) == 'FC-EtFe'
    assert F.fix_comparator(s, '14.8 times', 'FC-Et', cands) == 'FC-EtFe'
    assert F.fix_comparator(s, '58.9 MJ/m3', 'FC-EtFe', cands) == 'FC-EtFe', '主语样品原样不动'


def test_对照样_数在对照样后面说的就是它():
    s = 'Compared with FC-1T, FC-Et showed 3.2 MPa and FC-1T only 0.5 MPa.'
    assert F.fix_comparator(s, '0.5 MPa', 'FC-1T', ['FC-1T', 'FC-Et']) == 'FC-1T'


def test_测试手段与性质名不当样品():
    for bad in ('Stress-relaxation', 'DMA', 'SEM', 'Tensile strength'):
        assert not F._looks_like_sample(bad), bad
    for ok in ('PBS-1', 'FC-EtFe', 'PVA/CPO', 'CAN-4-3-30'):
        assert F._looks_like_sample(ok), ok
