# -*- coding: utf-8 -*-
"""整篇卡片（2026-09-23）：脚本那一半 —— 键家族要有原文关键词、字段核对、假模型走通。"""
from shared.domain import schema
from tools.extract import paper_card as PC

TEXT = ('Title: Boronic ester vitrimers\n\nAbstract: We report a polydimethylsiloxane elastomer crosslinked by '
        'dynamic boronic ester bonds and hydrogen bonding, reaching 12.5 MPa strength.\n\nConclusion: (none)')


def test_英文名都被自己的家族正则认出():
    for zh, en in PC.BOND_EN.items():
        assert zh in schema.bond_families(en), (zh, en)
    assert list(PC.BOND_EN) == [n for n, _ in schema.BOND_FAMILIES], '与词表同序同名'


def test_模型选的家族没有原文关键词就拿掉():
    kept, dropped = PC.pick_bonds('boronic ester; hydrogen bond; disulfide', TEXT)
    assert kept == ['氢键', '硼酸酯'] and dropped == ['二硫键']
    assert PC.pick_bonds('none', TEXT) == ([], [])


def test_字段核对_材料不在原文清空_数字编的清空():
    card, checks = PC.check_card({'material_system': 'PDMS elastomer with boronic ester', 'self_healing': 'yes: bond exchange',
                                  'key_finding': 'Strength reaches 99.9 MPa.', 'limitation': ''}, TEXT)
    assert card['material_system'] and checks['material_system_grounded']
    assert card['key_finding'] == '' and not checks['key_finding_numbers_ok']
    assert card['limitation'] == 'N/A'
    card, checks = PC.check_card({'material_system': 'zzzz qqqq', 'self_healing': 'maybe'}, TEXT)
    assert card['material_system'] == '' and card['self_healing'] == ''


def test_假模型走通_落成老记录能认的形状():
    md = ('# Boronic ester vitrimers\n\n## Abstract\n\n' + TEXT.split('Abstract: ')[1].split('\n\nConclusion')[0] * 3
          + '\n\n## Conclusion\n\nThe elastomer heals at room temperature.\n')

    def chat(system, user, **kw):
        return 'boronic ester; disulfide'

    def chat_json(system, user, **kw):
        return {'material_system': 'polydimethylsiloxane elastomer', 'self_healing': 'yes: boronic ester exchange',
                'key_finding': 'Strength reaches 12.5 MPa.', 'limitation': 'N/A'}
    c = PC.make_card(md, {'title': 'Boronic ester vitrimers'}, chat, chat_json, 'm', doc_type='research')
    assert c['bond_families'] == ['硼酸酯'] and c['checks']['bonds_dropped_no_evidence'] == ['二硫键']
    # 概念矩阵用正则归并 dynamic_bond_type：写进去的英文名要能被认回同一个家族
    assert schema.bond_families(c['dynamic_bond_type']) == ['硼酸酯']
    assert c['key_finding'] and c['doc_type'] == 'research'
