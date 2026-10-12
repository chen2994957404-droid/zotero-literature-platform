# -*- coding: utf-8 -*-
"""文献编号改名（host.deploy.rekey）—— 全离线：临时目录里造一篇 Zotero 编号的文献，改过去再改回来。"""
import io
import json
import os
import sqlite3

import pytest

from shared.kernel import catalog, paths
from host.deploy import rekey

DOI = '10.1021/acs.macromol.6c00733'
OLD = 'ABCD1234'


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ('RAW', 'CURATED', 'STATE', 'SERVING'):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(paths, name, str(d))
    monkeypatch.setattr(paths, 'STRUCTURED', str(tmp_path / 'serving' / 'structured'))
    os.makedirs(paths.STRUCTURED)
    catalog._cache_clear()
    catalog.register(OLD, doi=DOI, title='t', zotero_key=OLD)
    os.makedirs(paths.paper_raw_dir(OLD))
    io.open(paths.local_pdf(OLD), 'w').write('pdf')
    io.open(paths.structured(OLD), 'w').write('{}')
    io.open(paths.evalset(), 'w', encoding='utf-8').write(json.dumps({'items': [{'key': OLD}]}))
    io.open(paths.compare('compare_PBS'), 'w', encoding='utf-8').write(f'| {OLD} | x |\n| {OLD}X | y |\n')
    json.dump({'papers': {OLD: {'doi': DOI}}}, io.open(paths.oa_index(), 'w', encoding='utf-8'))
    con = sqlite3.connect(paths.state_db())
    con.execute('create table runs (item_key text, step text)')
    con.execute('insert into runs values (?, ?)', (OLD, 'main_summary'))
    con.commit()
    yield con
    con.close()
    catalog._cache_clear()


def test_计划_要改的与跳过的(env):
    catalog.register('EFGH5678', title='没 DOI')
    todo, skip = rekey.plan()
    assert todo == [(OLD, paths.paper_id_from_doi(DOI), catalog.norm_doi(DOI))]
    assert ('EFGH5678', '没有 DOI') in skip


def test_改过去再改回来_各处都跟着变(env):
    new = paths.paper_id_from_doi(DOI)
    r = rekey.move_one(OLD, new, store=None, con=env)
    catalog._cache_clear()
    assert os.path.isfile(paths.local_pdf(new)) and not os.path.exists(paths.paper_raw_dir(OLD))
    assert catalog.read_meta(new)['key'] == new and catalog.read_meta(new)['zotero_key'] == OLD
    assert catalog.resolve(OLD) == new                                   # 旧编号还认得
    assert os.path.isfile(paths.structured(new))
    assert env.execute('select item_key from runs').fetchone()[0] == new
    assert new in json.load(io.open(paths.oa_index(), encoding='utf-8'))['papers']
    md = io.open(paths.compare('compare_PBS'), encoding='utf-8').read()
    assert f'| {new} |' in md and f'| {OLD}X |' in md                    # 只换整词，不误伤别的编号
    assert r['text_hits'] == 2                                           # evalset 一处 + 对比表一处

    rekey.move_one(new, OLD, store=None, con=env)
    catalog._cache_clear()
    assert os.path.isfile(paths.local_pdf(OLD)) and not os.path.exists(paths.paper_raw_dir(new))
    assert env.execute('select item_key from runs').fetchone()[0] == OLD
    assert catalog.read_meta(OLD)['key'] == OLD


def test_目标已存在就跳过(env):
    catalog.register(paths.paper_id_from_doi(DOI), doi=DOI, title='另一份')
    todo, skip = rekey.plan()
    assert not todo and skip and '已存在' in skip[0][1]
