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


def test_考卷金标形状完整_评分器能跑():
    from tools.extract.evals import holdout as H
    papers = H.load_gold()
    assert len(papers) >= 5
    for p in papers:
        assert p['core'] and all('quote' in g for g in p['core'] + p['edge'] + p['negative'])
        assert all(g.get('why') for g in p['edge'] + p['negative'])
    g = papers[0]
    rows = H.rows_from_facts([{'where': 'main', 'norm': str(c['value']), 'sample': c['sample_id'], 'property': c['name']}
                              for c in g['core']] + [{'where': 'si', 'norm': '1', 'sample': 'x', 'property': 'y'}])
    from tools.extract.evals.scorers.measurements import score_paper
    s = score_paper(g, rows)
    assert s['recall'] == 1.0 and s['precision'] == 1.0, '金标自己喂回去必须满分；SI 的行不参与'


# ── 第 2 步（2026-09-24，练习金标上找到的通用毛病）─────────────────

def test_分别为_按顺序配样品():
    c = scan.clean_body('The Ge,exp values for PBS1 to PBS6 are 243, 129, 73, 71, 91, and 112 kPa, respectively. It')
    got = [(n['raw'], n.get('sample_hint')) for n in sorted(scan.scan_numbers(c), key=lambda n: n['pos'])]
    assert got == [('243 kPa', 'PBS1'), ('129 kPa', 'PBS2'), ('73 kPa', 'PBS3'), ('71 kPa', 'PBS4'),
                   ('91 kPa', 'PBS5'), ('112 kPa', 'PBS6')], got
    c = scan.clean_body('The strengths of SPU, SPU/5D-SiO2 and SPU/10D-SiO2 are 9.8, 12.1 and 19.5 MPa, respectively.')
    assert [n.get('sample_hint') for n in sorted(scan.scan_numbers(c), key=lambda n: n['pos'])] == ['SPU', 'SPU/5D-SiO2', 'SPU/10D-SiO2']
    c = scan.clean_body('The values for A and B are 1.2 and 3.4 and 5.6 MPa, respectively.')     # 个数对不上就不配
    assert not any(n.get('sample_hint') for n in scan.scan_numbers(c))


def test_科学计数法与负数():
    c = scan.clean_body(r'sensitive toward fluoride ions ( $1\times10^{-10}$ M and $2 \times 10^{-9}$ M) with the slope of -23 mV per decade')
    vals = [n['value'] for n in scan.scan_numbers(c)]
    assert 1e-10 in vals and 2e-9 in vals and -23.0 in vals and 1.0 not in vals and 2.0 not in vals, vals


def test_引言里别人的数_方法节_HTML表格():
    assert F._others_work('Previous CMDMs reached 797.4 MPa [19].')
    assert F._others_work('Such elastomers typically show <150 MPa-1.')
    assert not F._others_work('Herein, we achieve 30.80 mV K-1 [3].'), '我们自己说的不算'
    assert not F._others_work('As a result, LCN shows a 1700% variation in Young modulus.')
    t = 'text 5 MPa <table><tr><td>7 MPa</td></tr></table> after 9 MPa'
    assert not F._in_html_table(t, t.find('5 MPa')) and F._in_html_table(t, t.find('7 MPa')) and not F._in_html_table(t, t.find('9 MPa'))


def test_样品名_单位碎片与化学式下标():
    for bad in ('MJ', 'K-1', 'kPa', 'TEM'):
        assert not F._looks_like_sample(bad), bad
    for ok in ('EN', 'PVA', 'PU', 'S1', 'A1', 'PBS1'):
        assert F._looks_like_sample(ok), ok
    assert F._join_formula('SPU/10D-SiO 2 reaches 19.5 MPa; Figure 2 shows') == 'SPU/10D-SiO2 reaches 19.5 MPa; Figure 2 shows'


def test_召回修正三条():
    assert F._names_property({'unit': 's', 'context': 'the relaxation time of PBS1 is 1.08 s'})
    assert F._names_property({'unit': 's', 'context': 'no name here', 'sample_hint': 'PBS1'})
    assert not F._names_property({'unit': 'h', 'context': 'stirred at 80 C for 12 h, tensile strength'})
    win = 'The tensile strength for SPU/10D-SiO2 reaches 19.5 MPa, 2 times higher than SPU.'
    assert F._prefer_longest(['D-SiO2', 'SPU'], win) == ['SPU/10D-SiO2', 'SPU']
    from tools.extract.evals.scorers.measurements import _same_sample
    assert _same_sample('polymer 1', '1') and not _same_sample('polymer 2', '1')


def test_证据够就收_与完整名字():
    for t, raw, want in [('In the S1 sample, the energy dissipation ratio of 88% is achieved', '88%', 'energy dissipation ratio'),
                         ('The tensile strength of SPU is 9.8 MPa and elongation at break of 3052%.', '3052%', 'elongation at break'),
                         ('The samples were stirred for 12 h at 80 °C before testing the tensile strength.', '80 °C', None)]:
        c = next(c for c in scan.scan_numbers(t) if c['raw'] == raw)
        got = F.evidence_property(t, c)
        assert (got == want) if want is None else (got and want in got), (t, got)
    assert F._mentions('strength of spu/10d-sio2 rises', 'spu/10d-sio2') and not F._mentions('strength of spu/10d-sio2 rises', 'spu')
