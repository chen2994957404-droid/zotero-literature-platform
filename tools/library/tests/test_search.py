# -*- coding: utf-8 -*-
"""证据库检索（tools.library.dbsearch）—— 纯函数部分，全离线。"""
from tools.library import dbsearch as search


def test_doi识别():
    assert search.is_doi('https://doi.org/10.1021/jacs.3c13392')
    assert search.is_doi('10.1002/adma.202521208')
    assert not search.is_doi('ionic skin 2024')


def test_归一_连字符与重音与大小写():
    assert search.norm('Shu‐Hong Yu') == search.norm('shuhong yu')
    assert search.norm('Self-Healing') == 'selfhealing'
    assert search.norm('Ruìxué Bái') == 'ruixue bai'
    assert search.norm('武培怡') == '武培怡'


def test_人名不管顺序():
    assert search._name_hit(search.tokens('Wu Peiyi'), 'Peiyi Wu')
    assert search._name_hit(search.tokens('peiyi wu'), 'Peiyi Wu')
    assert not search._name_hit(search.tokens('Wu Kai'), 'Peiyi Wu')


def test_中文名经名单换编号():
    roster = {'teams': [{'leader': {'name': 'Peiyi Wu', 'name_zh': '武培怡', 'openalex': ['A1']},
                         'members': [], 'alumni': [], 'pending': []}]}
    authors = [{'n': 'Peiyi Wu', 'id': 'A1', 'c': True, 'p': 'last'}]
    assert search._person_match('武培怡', authors, roster)
    assert not search._person_match('孙胜童', authors, roster)
    assert search._person_match('Wu Peiyi', authors, roster)


def test_目录卡缓存_没变化不重扫_过期或增删才重扫(monkeypatch):
    calls = []
    monkeypatch.setattr(search.catalog, 'scan', lambda: calls.append(1) or [{'id': 'X'}])
    stamp = [(1, 1)]
    monkeypatch.setattr(search, '_catalog_dirs_stamp', lambda: stamp[0])
    search._CACHE.clear()
    search._scan(); search._scan()
    assert len(calls) == 1                      # 第二次走缓存
    stamp[0] = (1, 2)                           # 有文献增删
    search._scan()
    assert len(calls) == 2
    monkeypatch.setattr(search, 'SCAN_TTL', -1) # 过期
    search._scan()
    assert len(calls) == 3
    search._CACHE.clear()
