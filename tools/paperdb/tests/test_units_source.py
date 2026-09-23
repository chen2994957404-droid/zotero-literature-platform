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


def test_整篇卡片补整篇级字段_老记录有值的不动(monkeypatch, tmp_path):
    import json
    import tools.paperdb as P
    from shared.kernel import catalog
    cards = {'OLD00001': {'dynamic_bond_type': 'boronic ester', 'material_system': 'X', 'key_finding': 'kf'},
             'NEW00002': {'dynamic_bond_type': 'hydrogen bond', 'material_system': 'polyurea', 'doc_type': 'research'}}
    for k, c in cards.items():
        (tmp_path / k).write_text(json.dumps(c), encoding='utf-8')
    monkeypatch.setattr(P.paths, 'all_keys', lambda: list(cards))
    monkeypatch.setattr(P.paths, 'card', lambda k: str(tmp_path / k))
    monkeypatch.setattr(P.paths, 'si_fulltext', lambda k: str(tmp_path / 'nope'))
    monkeypatch.setattr(catalog, 'read_meta', lambda k: {'title': 'New paper', 'doi': '10.1/new'})
    monkeypatch.setattr(catalog, 'doi_of', lambda m: m.get('doi', ''))
    recs = P._with_cards([{'key': 'OLD00001', 'dynamic_bond_type': 'B-O-B', 'material_system': 'N/A'}])
    old, new = recs
    assert old['dynamic_bond_type'] == 'B-O-B' and old['material_system'] == 'X' and old['key_finding'] == 'kf'
    assert new['key'] == 'NEW00002' and new['title'] == 'New paper' and new['source'] == 'local'
    assert new['dynamic_bond_type'] == 'hydrogen bond'
