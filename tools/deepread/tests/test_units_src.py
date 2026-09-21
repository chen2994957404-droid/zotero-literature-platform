# -*- coding: utf-8 -*-
"""原文单元 + 覆盖配对（2026-09-20）：切片、九类解析、数值/名字/图号/语义四种配法。模型与向量都换成假替身。"""
from tools.deepread.evals import units_src as US
from tools.deepread.tests.test_sectioned import MD
from shared.domain.schema import outline as ol


def test_切片_图注单独成片_参考文献不进():
    ps = US.pieces(MD, ol.build_outline(MD), si_md='SI synthesis: 0.5 g PDMS at 180 °C.')
    kinds = [k for k, _, _, _ in ps]
    assert 'caption' in kinds and 'si' in kinds
    assert not any('797.4' in t for _, _, t, _ in ps)      # 参考文献里的数不进任何片


def test_覆盖_四种配法():
    ref = [{'type': 'fact', 'sample': 'PBS', 'property': '强度', 'value': '12.5', 'unit': 'MPa'},
           {'type': 'fact', 'sample': 'PBS', 'property': '模量', 'value': '99', 'unit': 'MPa'},
           {'type': 'entity', 'name': '硼酸', 'abbr': 'PDMS'},
           {'type': 'panel', 'figure': '1', 'subpanel': 'a', 'shows': '曲线'},
           {'type': 'claim', 'text': '动态交换耗散能量'},
           {'type': 'action', 'action': '进行拉伸测试', 'materials': []}]        # 复分类成 method
    src = [{'type': 'fact', 'sample': 'PBS', 'property': 'strength', 'value': '12.5', 'unit': 'MPa'},
           {'type': 'entity', 'name': 'polydimethylsiloxane', 'abbr': 'PDMS'},
           {'type': 'panel', 'figure': '1', 'subpanel': 'a', 'shows': 'stress-strain'},
           {'type': 'claim', 'text': 'dynamic exchange dissipates energy'},
           {'type': 'method', 'technique': 'tensile test', 'measures': 'strength'}]
    vec = {'text: 动态交换耗散能量': [1, 0], 'text: dynamic exchange dissipates energy': [1, 0],
           'technique: tensile test ; measures: strength': [0, 1]}

    def embed(texts):
        return [vec.get(t, [0.3, 0.3]) for t in texts]
    m = US.match_paper(ref, src, embed)
    hows = [r['how'] for r in m]
    assert hows[0] == 'num' and hows[1] == 'none' and hows[2] == 'name' and hows[3] == 'panel'
    assert hows[4] == 'sim' and m[5]['type'] == 'method'


def test_判同异_召回前三并按模型答案计覆盖(tmp_path, monkeypatch):
    import json, io, os
    from shared.kernel import paths
    monkeypatch.setattr(paths, 'STATE', str(tmp_path))
    d = paths.unit_study_dir('t'); os.makedirs(d)
    ref = [{'type': 'claim', 'text': '动态交换耗散能量'}, {'type': 'role', 'component': 'PDMS', 'function': '骨架'}]
    src = [{'type': 'claim', 'text': 'dynamic exchange dissipates energy'}, {'type': 'claim', 'text': 'unrelated'},
           {'type': 'role', 'component': 'boric acid', 'function': 'crosslinker'}]
    json.dump({'units': ref}, io.open(os.path.join(d, 'P.json'), 'w', encoding='utf-8'))
    json.dump({'units': src}, io.open(os.path.join(d, 'P.src.json'), 'w', encoding='utf-8'))
    vec = {'text: 动态交换耗散能量': [1, 0], 'text: dynamic exchange dissipates energy': [1, 0], 'text: unrelated': [0, 1],
           'component: PDMS ; function: 骨架': [0, 1], 'component: boric acid ; function: crosslinker': [0.5, 0.5]}
    def embed(texts):
        return [vec.get(t, [0.2, 0.2]) for t in texts]
    def chat_json(sysp, user, **kw):
        return {'match': 1} if '耗散' in user else {'match': 0}
    per_type, results = US.judge_coverage('t', chat_json, 'fake', embed=embed, log=lambda *a: None)
    assert per_type['claim']['rate'] == 1.0 and per_type['role']['rate'] == 0.0
    assert results[0]['picked'].startswith('text: dynamic') and os.path.exists(os.path.join(d, 'coverage_judged_fake.md'))
