# -*- coding: utf-8 -*-
"""paperdb 读单元库（2026-09-22，抽取收成一条线的第一步）。"""


def test_单元库的数值事实并进数值库_量纲没过的不要(monkeypatch):
    """抽取收成一条线的第一步（2026-09-22）：单元库是新数据唯一的来源。"""
    import tools.paperdb as P
    from shared.kernel import units_store
    units = [
        {'type': 'fact', 'fields': {'sample': 'FC-EtFe', 'property': 'tensile strength', 'value': '7.11 MPa', 'unit': 'MPa'},
         'src': {'where': 'main', 'location': 'Fig. 2'}, 'checks': {'dimension_ok': True}},
        {'type': 'fact', 'fields': {'sample': 'FC-EtFe', 'property': 'tensile strength', 'value': '5 mm', 'unit': 'mm'},
         'src': {}, 'checks': {'dimension_ok': False}},
        {'type': 'action', 'fields': {'action': 'stir'}},
    ]
    monkeypatch.setattr(P.paths, 'all_keys', lambda: ['ABCD1234'])
    monkeypatch.setattr(units_store, 'load', lambda key: units)
    rows = P._unit_measurements()['ABCD1234']
    assert len(rows) == 1
    r = rows[0]
    assert r['sample_id'] == 'FC-EtFe' and r['value'] == 7.11 and r['unit'] == 'MPa'
    assert r['method'] == 'units' and r['location'] == 'Fig. 2'
