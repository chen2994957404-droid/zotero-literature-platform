# -*- coding: utf-8 -*-
"""专题（tools.library.topics）—— 全离线：临时目录里造两篇文献。"""
import pytest

from shared.kernel import catalog, paths
from tools.library import topics

DOI_A, DOI_B = '10.1021/acs.macromol.6c00733', '10.1002/adma.202521208'


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ('RAW', 'CURATED', 'STATE'):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(paths, name, str(d))
    catalog._cache_clear()
    for d in (DOI_A, DOI_B):
        catalog.register(paths.paper_id_from_doi(d), doi=d, title='t ' + d)
    yield
    catalog._cache_clear()


def test_加文献_不存在就新建_DOI各种写法都认_库里没有的如实报(env):
    r = topics.add('综述：硼酸酯', ['https://doi.org/' + DOI_A, 'doi_10.1002-adma.202521208', '10.9999/none'],
                   note='第 3 节', by='Claude Science')
    assert r['topic'] == '综述：硼酸酯'
    assert sorted(r['added']) == sorted(paths.paper_id_from_doi(d) for d in (DOI_A, DOI_B))
    assert r['missing'] == ['10.9999/none']
    t = topics.list_topics()
    assert len(t) == 1 and t[0]['n'] == 2 and t[0]['created_by'] == 'Claude Science'


def test_重复加不重复_备注会更新(env):
    topics.add('X', [DOI_A])
    r = topics.add('X', [DOI_A], note='新备注')
    assert r['already'] and not r['added']
    assert topics.items('X')[0]['note'] == '新备注'


def test_拿掉_删专题_文献本身不动(env):
    topics.add('X', [DOI_A, DOI_B])
    topics.remove('X', [DOI_A])
    assert topics.pids('X') == {paths.paper_id_from_doi(DOI_B)}
    assert topics.topics_of(paths.paper_id_from_doi(DOI_B))[0]['name'] == 'X'
    assert topics.delete_topic('X') and topics.list_topics() == []
    assert catalog.find(DOI_A)                                   # 文献还在证据库里


def test_改名与说明(env):
    topics.add('X', [DOI_A], topic_note='写综述用')
    topics.rename('X', 'Y')
    y = topics.get('Y')
    assert y is not None and y['note'] == '写综述用' and topics.get('X') is None
    assert topics.membership() == {paths.paper_id_from_doi(DOI_A): ['Y']}
