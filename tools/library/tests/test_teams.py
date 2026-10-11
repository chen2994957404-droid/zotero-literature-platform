# -*- coding: utf-8 -*-
"""文章挂团队（tools.library.teams）—— 全离线：假名单 + 假 OpenAlex work。

守的是第十节试验得出的几条规则：末位且通讯者优先；末位是名单外的人时，名单里的共同通讯只算合作；
末位不是通讯时按通讯找；小导归组；已独立的人 since 年起不再算老组。"""
from tools.library import teams

ROSTER = {'teams': [
    {'leader': {'name': 'Big A', 'openalex': ['A1']},
     'members': [{'name': 'Junior B', 'openalex': ['B1', 'B2']}],
     'alumni': [{'name': 'Grad C', 'openalex': ['C1'], 'since': 2023}]},
    {'leader': {'name': 'Grad C', 'openalex': ['C1']}},
    {'leader': {'name': 'Star S', 'openalex': ['S1']}},
]}
IDX = teams.person_index(ROSTER)


def au(aid, corr=False, name=None):
    return {'author': {'id': 'https://openalex.org/' + aid, 'display_name': name or aid},
            'is_corresponding': corr, 'author_position': 'middle'}


def work(year, *authors):
    return {'publication_year': year, 'authorships': list(authors)}


def test_末位且通讯的大导是主组():
    r = teams.link_work(work(2024, au('X9'), au('A1', True)), IDX)
    assert r['primary'] == 0 and r['others'] == []


def test_小导当末位也归他的组():
    r = teams.link_work(work(2024, au('X9'), au('A1', True), au('B2', True)), IDX)
    assert r['primary'] == 0


def test_末位是名单外的人_名单里的共同通讯只算合作():
    r = teams.link_work(work(2024, au('X9'), au('S1', True), au('Z9', True)), IDX)
    assert r['primary'] is None and r['others'] == [2]


def test_末位不是通讯_按通讯作者找():
    r = teams.link_work(work(2024, au('A1', True), au('X9')), IDX)
    assert r['primary'] == 0


def test_独立之前算老组_之后算新组():
    before = teams.link_work(work(2021, au('X9'), au('C1', True)), IDX)
    after = teams.link_work(work(2024, au('X9'), au('C1', True)), IDX)
    assert before['primary'] == 0 and 1 in before['others']
    assert after['primary'] == 1 and 0 not in after['others']


def test_跟名单无关():
    r = teams.link_work(work(2024, au('X9'), au('Y9', True)), IDX)
    assert r == {'primary': None, 'others': [], 'via': ''}


def test_没标通讯时以末位为准():
    r = teams.link_work(work(2024, au('X9'), au('B1')), IDX)
    assert r['primary'] == 0
