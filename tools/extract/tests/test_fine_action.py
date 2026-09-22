# -*- coding: utf-8 -*-
"""fine_action 的离线测试：候选句筛选、从句切分、槽位核对、落库形状。不调模型。"""
from tools.extract import fine_action as A

SI = """Materials

PTMEG and MDI were purchased from Aladdin and used as received.

Synthesis of the PUU Elastomer

PTMEG (20 g, 10 mmol) was dried under vacuum at 120 °C for 2 h to remove residual moisture. After cooling to 80 °C, HMDI (5.3 g, 20 mmol) was added, and the mixture was stirred at 80 °C for 2 h under nitrogen, yielding an isocyanate-terminated prepolymer.

Characterization

FT-IR spectra were recorded on a Bruker VERTEX 80 V spectrometer.
"""


def test_候选只留步骤句_不留原料来源与仪器句():
    c = [s for _, _, s in A.candidates('', SI)]
    joined = ' | '.join(c)
    assert 'was dried under vacuum' in joined
    assert 'purchased' not in joined and 'spectrometer' not in joined


def test_一句两个动作切成两条从句():
    s = 'After cooling to 80 °C, HMDI (5.3 g, 20 mmol) was added, and the mixture was stirred at 80 °C for 2 h under nitrogen.'
    parts = A.clauses(s)
    assert len(parts) == 2 and 'was added' in parts[0] and 'was stirred' in parts[1]


def test_核对_不在句里的量与材料扔掉_动作退回正则():
    sent = 'PTMEG (20 g, 10 mmol) was dried under vacuum at 120 °C for 2 h.'
    d = {'action': 'was heated', 'materials': 'PTMEG, MDI', 'amounts': '20 g, 10 mmol, 5 g', 'conditions': '120 °C, 2 h, 24 h', 'product': 'prepolymer'}
    v = A.verify(sent, d)
    assert v['action'] == 'was dried'
    assert v['materials'] == ['PTMEG']
    assert v['amounts'] == ['20 g', '10 mmol'] and v['conditions'] == ['120 °C', '2 h']
    assert v['product'] == ''


def test_落库形状():
    steps = [{'where': 'si', 'order': 1, 'sent': 'X was added.', 'action': 'was added', 'materials': ['X'],
              'amounts': ['1 g'], 'conditions': [], 'product': ''}]
    u = A.to_units(steps, 'm')
    assert len(u) == 1 and u[0]['type'] == 'action' and u[0]['fields']['materials'] == ['X'] and u[0]['by']['producer'] == 'fine_action'


def test_extract_paper_用假模型走通(monkeypatch):
    def fake_chat(sysp, user, **kw):
        return 'action: was dried\nmaterials: PTMEG\namounts: 20 g, 10 mmol\nconditions: 120 °C, 2 h\nproduct: none'
    steps, st = A.extract_paper('', fake_chat, 'm', log=lambda *a: None, si_md=SI)
    assert st['cands'] >= 3 and steps and steps[0]['amounts'] == ['20 g', '10 mmol']
