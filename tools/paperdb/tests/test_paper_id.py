# -*- coding: utf-8 -*-
"""查询库不再只装「他 Zotero 里的文献」（2026-09-07 身份证放宽）。

守的是这个决定：**数据库是这个领域的公共账本，Zotero 是它的一个来源。**
所以 `papers.key` 是来源无关的文献 id，「在不在他自己库里」由 `zotero_key` 单独回答，
跨来源对账靠 `doi`。谁把它改回「只认 8 位 Zotero 编号」，这里会红。
"""
import io
import json

import pytest

from shared.kernel import paths
from tools import paperdb


@pytest.fixture
def db(isolate):
    return isolate


def _write(st, key, **kw):
    rec = dict({'key': key, 'title': '标题', 'schema_ver': 1}, **kw)
    io.open(st / f'{key}.json', 'w', encoding='utf-8').write(
        json.dumps(rec, ensure_ascii=False))


def test_三种来源的文献能住进同一张表(db):
    doi_id = paths.paper_id_from_doi('10.1021/acs.macromol.1c00123')
    _write(db, 'AAAA1111', doi='10.1000/mine')      # 他收藏的
    _write(db, 'W2741809687', doi='10.1000/oa')     # 方向层的公开文献
    _write(db, doi_id, doi='10.1021/acs.macromol.1c00123')   # 只知道 DOI 的
    rows = {r['key']: r for r in paperdb.query('SELECT key, zotero_key FROM papers')}
    assert set(rows) == {'AAAA1111', 'W2741809687', doi_id}


def test_zotero_key只对他自己库里的那些非空(db):
    """这一列的意思是「这篇在我的阅读桌上」，不是「这篇有编号」。"""
    _write(db, 'AAAA1111')
    _write(db, 'W2741809687')
    rows = {r['key']: r['zotero_key'] for r in
            paperdb.query('SELECT key, zotero_key FROM papers')}
    assert rows['AAAA1111'] == 'AAAA1111'
    assert not rows['W2741809687']


def test_对账靠DOI(db):
    """同一篇文献两个来源各进了一条 —— 认出它们是同一篇，只能靠 DOI。"""
    same = '10.1021/acs.macromol.1c00123'
    _write(db, 'AAAA1111', doi=same)
    _write(db, paths.paper_id_from_doi(same), doi=same)
    n = paperdb.query('SELECT COUNT(*) c FROM papers WHERE doi = ?', (same,))[0]['c']
    assert n == 2
