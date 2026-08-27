# -*- coding: utf-8 -*-
"""adapters.vectordb 的测试。

这些测试**建一个真的 Chroma 库**（在 pytest 的临时目录里，用假向量），
所以是真验证而不是 mock 自嗨 —— 而且全程本地、不联网、不碰用户数据，
仍然属于离线档。
"""
import pytest

from adapters import vectordb
from core import errors


# ⚠ Chroma 只接受 3~512 位 ASCII 集合名，中文名会被拒（实测得出）。
#    所以测试集合名用 ASCII —— 真实集合名 'literature' 本来就是 ASCII。
TEST_COLL = 'test_coll'


@pytest.fixture
def store(tmp_path):
    pytest.importorskip('chromadb')
    return vectordb.open_store(path=str(tmp_path / 'vdb'), name=TEST_COLL)


def _vec(*xs):
    """凑一个 4 维向量，够用来测检索排序。"""
    return list(xs) + [0.0] * (4 - len(xs))


@pytest.fixture
def filled(store):
    store.add(
        ids=['a', 'b', 'c'],
        documents=['聚硼硅氧烷的动态键', '环氧树脂固化', '完全无关的内容'],
        metadatas=[{'key': 'AAAAAAAA', 'title': '论文A'},
                   {'key': 'BBBBBBBB', 'title': '论文B'},
                   {'key': 'CCCCCCCC', 'title': '论文C'}],
        embeddings=[_vec(1, 0, 0), _vec(0, 1, 0), _vec(0, 0, 1)],
    )
    return store


class TestBasics:
    def test_空库计数为零(self, store):
        assert store.count() == 0

    def test_入库后计数正确(self, filled):
        assert filled.count() == 3

    def test_入库空列表不报错(self, store):
        assert store.add([], [], [], []) == 0

    def test_四个列表不等长直接报错(self, store):
        """静默入错比报错糟得多 —— 会在检索时才表现为结果莫名其妙。"""
        with pytest.raises(errors.BadInputError):
            store.add(['a', 'b'], ['x'], [{}], [_vec(1)])


class TestQuery:
    def test_检索返回拆平的结果没有chroma那层list(self, filled):
        hits = filled.query(_vec(1, 0, 0), n=2)
        assert isinstance(hits, list) and hits
        h = hits[0]
        assert set(h) == {'id', 'doc', 'meta', 'distance', 'sim'}

    def test_最像的排在最前(self, filled):
        hits = filled.query(_vec(1, 0, 0), n=3)
        assert hits[0]['id'] == 'a'
        assert hits[0]['doc'].startswith('聚硼硅氧烷')
        assert hits[0]['meta']['key'] == 'AAAAAAAA'

    def test_sim是越大越像(self, filled):
        hits = filled.query(_vec(1, 0, 0), n=3)
        sims = [h['sim'] for h in hits]
        assert sims == sorted(sims, reverse=True), sims
        assert 0.0 <= sims[-1] <= sims[0] <= 1.0

    def test_n为零返回空且不查库(self, filled):
        assert filled.query(_vec(1, 0, 0), n=0) == []

    def test_空库检索返回空列表而不是报错(self, store):
        assert store.query(_vec(1, 0, 0), n=5) == []


class TestIncremental:
    def test_能列出已入库的key(self, filled):
        assert filled.existing_keys() == {'AAAAAAAA', 'BBBBBBBB', 'CCCCCCCC'}

    def test_空库列key返回空集合(self, store):
        assert store.existing_keys() == set()

    def test_all_metadatas过滤掉空条目(self, filled):
        metas = filled.all_metadatas()
        assert len(metas) == 3 and all(m.get('title') for m in metas)


class TestRebuild:
    def test_rebuild清空旧数据(self, filled, tmp_path):
        again = vectordb.open_store(path=str(tmp_path / 'vdb'), name=TEST_COLL, rebuild=True)
        assert again.count() == 0

    def test_不rebuild则保留数据(self, filled, tmp_path):
        again = vectordb.open_store(path=str(tmp_path / 'vdb'), name=TEST_COLL)
        assert again.count() == 3


class TestHitNormalization:
    """_to_hits 是本适配层存在的理由，单独测它，不需要真库。"""

    def test_空返回不炸(self):
        assert vectordb._to_hits({}) == []
        assert vectordb._to_hits({'ids': [[]]}) == []

    def test_缺distances时sim为None(self):
        hits = vectordb._to_hits({'ids': [['x']], 'documents': [['d']],
                                  'metadatas': [[{'k': 1}]]})
        assert hits[0]['sim'] is None and hits[0]['distance'] is None

    def test_元数据为None时给空字典(self):
        """下游到处是 m['title']，给 None 会炸在很远的地方。"""
        hits = vectordb._to_hits({'ids': [['x']], 'documents': [['d']],
                                  'metadatas': [[None]], 'distances': [[0.1]]})
        assert hits[0]['meta'] == {}

    def test_距离转相似度被夹在0到1之间(self):
        hits = vectordb._to_hits({'ids': [['a', 'b']], 'documents': [['', '']],
                                  'metadatas': [[{}, {}]], 'distances': [[-0.2, 1.9]]})
        assert hits[0]['sim'] == 1.0 and hits[1]['sim'] == 0.0
