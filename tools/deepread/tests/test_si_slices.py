# -*- coding: utf-8 -*-
"""SI 切块（si_slices）与四栏拼装（si.compose）的离线测试：不联网、不调模型。"""
import re

from tools.deepread import si, si_slices

SI = """Supporting Information

Resolving the Trade-off in Elastomers

Xiang Wei, Tianqi Li, Yixuan Li, Junqi Sun*

State Key Laboratory of Supramolecular Structure and Materials, College of Chemistry, Jilin University

Table of contents

Materials

Synthesis of the PUU Elastomer

Material Characterization

Figure S1. FT-IR spectra of PUU.

References

Materials

PTMEG (Mn ~2000) and MDI were obtained from Aladdin Scientific Corp. and used as received.

Synthesis of the PUU Elastomer

PTMEG (20 g, 10 mmol) was dried under vacuum at 120 °C for 2 h. MDI (5.0 g, 20 mmol) was added and the mixture was stirred at 80 °C for 3 h.

Material Characterization

Tensile tests were performed on an INSTRON 5944 universal testing machine at 100 mm/min.

Figure S1. FT-IR spectra of PUU.

Table S1. Molecular weight of PUU.
<table><tr><td>Sample</td><td>Mn</td></tr><tr><td>PUU</td><td>52000</td></tr></table>

References

1. A. Author, B. Author, Some title. J. Chem. 12, 345 (2015).
"""


def test_四份材料各归各位():
    s = si_slices.slice(SI)
    assert 'Aladdin' in s['materials'][0][1]
    assert len(s['synthesis']) == 1 and '10 mmol' in s['synthesis'][0][1]
    assert 'INSTRON' in s['methods'][0][1]
    figs = s['figures'][0][1]
    assert 'Figure S1' in figs and '52000' in figs
    assert figs.count('Figure S1') == 1, '目录里那份题注要去重'
    joined = ' '.join(t for v in s.values() for _, t in v)
    assert 'Some title' not in joined, '参考文献要丢'
    assert 'Xiang Wei' not in joined and 'Jilin University' not in joined, '作者与单位要丢'


def test_目录里的References不吞掉后文():
    from tools.deepread.si_filter import filtered_text
    assert 'Aladdin' in filtered_text(SI)


def test_长节按块切_每块不超上限(monkeypatch):
    monkeypatch.setattr(si_slices, '_CHUNK', 300)
    long = 'Synthesis of X\n\n' + '\n\n'.join('Step %d: 1.0 g of A was added and stirred at 50 °C for 1 h.' % i for i in range(20))
    s = si_slices.slice(long)
    assert len(s['synthesis']) >= 3 and all(len(t) <= 300 + 40 for _, t in s['synthesis'])   # +40：块里带「## 标题」与段间空行


def test_compose_逐块调用_四栏拼装(monkeypatch):
    calls = []

    def fake_chat(sysp, user, **kw):
        calls.append(user)
        src = user.split('：\n\n', 1)[-1]
        nums = ' '.join(m.group(0) for m in re.finditer(r'\d+(?:\.\d+)?\s*[A-Za-z°%/]+', src))
        return '照搬的中文段落，' * 6 + nums

    monkeypatch.setattr(si, 'chat', fake_chat)
    content, st = si.compose(SI, None, log=lambda *a: None, n_figs=1)
    assert st['calls'] == 4 and not st['failed'] and not st['empty']
    for title in si.TITLES.values():
        assert title in content
    assert '20 mmol' in content


def test_compose_没材料的栏写未给出_全空才失败(monkeypatch):
    monkeypatch.setattr(si, 'chat', lambda *a, **k: '照搬的中文段落，' * 6)
    content, st = si.compose('Figure S1. A plot of something.', None, log=lambda *a: None)
    assert 'SI 未给出合成细节' in content and st['empty'] == ['materials', 'synthesis', 'methods']
    import pytest
    with pytest.raises(si.SIFailed):
        si.compose('', None, log=lambda *a: None)
