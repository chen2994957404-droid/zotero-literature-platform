# -*- coding: utf-8 -*-
"""给模型「自己用文献」补的三样（2026-09-14）：库内检索定位到节、参考文献认库、检索结果标可读。

全离线：向量库换成假的、目录指到临时目录。
"""
import io
import os

import pytest

from shared.kernel import catalog, paths
from tools import library

MD = '''# A tough elastomer

## 1. Introduction

Prior work by Zhang [1] used boronic esters; see also Wang et al. [2].

## 2. Results

''' + '\n\n'.join('Paragraph %d about boronic ester exchange with %d MPa strength %s.' % (i, i, 'y' * 500)
                  for i in range(1, 12)) + '''

## References

(1) Zhang, Y. Dynamic boronic ester networks. Macromolecules 2015, 48, 1234. https://doi.org/10.1021/acs.macromol.5b00210
(2) Wang, L. Some other paper. Polymer 2018, 9, 12.
(3) Li, Q. Self-healing polyurethane via boroxine bonds. Adv. Mater. 2016.
(4) A. B. Fourth entry. J. X. 2020.
(5) C. D. Fifth entry. J. Y. 2021.
'''


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ('RAW', 'CURATED', 'SERVING'):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(paths, name, str(d))
    monkeypatch.setattr(paths, 'STRUCTURED', str(tmp_path / 'serving' / 'structured'))
    key = 'AAAA0001'
    os.makedirs(paths.parsed_dir(key), exist_ok=True)
    io.open(paths.fulltext(key), 'w', encoding='utf-8').write(MD)
    catalog.register(key, doi='10.1000/self', title='A tough elastomer')
    # 证据库里另有两篇：一篇靠 DOI 对上 [1]，一篇靠标题对上 [3]
    catalog.register('BBBB0002', doi='10.1021/acs.macromol.5b00210', title='Dynamic boronic ester networks')
    catalog.register('CCCC0003', doi='10.1002/adma.x', title='Self-healing polyurethane via boroxine bonds')
    # 中文题名归一后是空串 —— 不许因此把每条参考文献都标成「已在库」（2026-09-14 真踩过）
    catalog.register('DDDD0004', doi='10.1002/x.y', title='基于含硼动态键的高性能自修复聚氨酯的制备与研究')
    return key


def test_参考文献按DOI和标题认出库里已有的(env):
    rows = library.refs(env)
    assert len(rows) == 5
    by = {r['n']: r for r in rows}
    assert by[1]['in_db'] and by[1]['id'] == 'BBBB0002' and by[1]['doi'] == '10.1021/acs.macromol.5b00210'
    assert by[3]['in_db'] and by[3]['id'] == 'CCCC0003', '没 DOI 的靠标题子串对上'
    assert not by[2]['in_db']
    assert not by[1]['text'].startswith('(1)'), '条目自己的编号不该重复显示'


def test_检索命中定位到节或段(env):
    doc = 'Paragraph 3 about boronic ester exchange with 3 MPa strength ' + 'y' * 500 + '.'
    addr = library._locate(env, doc, si=False)
    assert addr.startswith('s3'), addr                     # 2. Results 是第三节
    assert '.p' in addr, '长节要定位到段'
    assert library._locate(env, 'text that is nowhere in the paper at all ' * 3) == ''


def test_retrieve_不过大模型_每条带地址(env, monkeypatch):
    class FakeStore:
        def query(self, emb, n=6, where=None):
            return [{'doc': 'Paragraph 5 about boronic ester exchange with 5 MPa strength ' + 'y' * 500 + '.',
                     'meta': {'key': env, 'title': 'A tough elastomer', 'doi': '10.1000/self', 'source': 'main'},
                     'sim': 0.83}]
    closed = []
    monkeypatch.setattr('shared.adapters.vectordb.open_store', lambda *a, **k: FakeStore())
    monkeypatch.setattr('shared.adapters.vectordb.close_all', lambda: closed.append(1))
    monkeypatch.setattr('shared.adapters.embed.embed', lambda texts: [[0.1] * 4 for _ in texts])
    rows = library.retrieve('boronic ester exchange', n=3)
    assert rows[0]['id'] == env and rows[0]['address'].startswith('s3.p')
    assert closed, '常驻进程用完向量库必须放掉连接（踩坑 #157）'
    txt = library.render_retrieve(rows, 'boronic ester exchange')
    assert 'library_section' in txt and rows[0]['address'] in txt
