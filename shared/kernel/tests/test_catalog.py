# -*- coding: utf-8 -*-
"""证据库目录：**「有没有这篇」先问本地**（2026-09-13 用户拍板：证据库是全集，Zotero 是子集）。

全离线：目录指到临时目录，不碰真实数据、不问 Zotero。
"""
import io
import os

import pytest

from shared.kernel import catalog, paths

DOI = '10.1021/acs.macromol.5b00210'


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ('RAW', 'CURATED', 'SERVING'):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(paths, name, str(d))
    monkeypatch.setattr(paths, 'STRUCTURED', str(tmp_path / 'serving' / 'structured'))
    return tmp_path


def test_登记后按DOI查得到_且DOI归一(env):
    pid = paths.paper_id_from_doi(DOI)
    catalog.register(pid, doi='https://doi.org/' + DOI.upper(), title='T', year='2015')
    assert catalog.find(DOI) == pid
    assert catalog.find('DOI:' + DOI) == pid, 'URL 前缀 / 大小写都不该影响对账'
    assert catalog.find('10.9999/nothing') == ''


def test_只补不覆盖(env):
    pid = 'AAAA1111'
    catalog.register(pid, doi=DOI, title='用户改过的标题')
    catalog.register(pid, doi=DOI, title='Crossref 给的标题', journal='Macromolecules')
    m = catalog.read_meta(pid)
    assert m['title'] == '用户改过的标题', '已有的值不许被后来的登记冲掉'
    assert m['journal'] == 'Macromolecules', '空缺的要补上'
    catalog.register(pid, title='明确要改', overwrite=True)
    assert catalog.read_meta(pid)['title'] == '明确要改'


def test_老数据的大写DOI键也认(env):
    """精读流水线写的 meta.json 用的是 `DOI` 键 —— 目录必须认得老数据。"""
    pid = 'BBBB2222'
    os.makedirs(paths.paper_dir(pid))
    io.open(paths.meta(pid), 'w', encoding='utf-8').write(
        '{"key": "BBBB2222", "title": "old", "DOI": "%s", "date": "2025-11"}' % DOI.upper())
    r = catalog.record(pid)
    assert r['doi'] == DOI and r['year'] == 2025 and r['in_zotero']
    assert catalog.find(DOI) == pid


def test_目录卡如实反映手上有什么(env):
    pid = paths.paper_id_from_doi(DOI)
    catalog.register(pid, doi=DOI, title='T')
    r = catalog.record(pid)
    assert not r['pdf'] and not r['fulltext'] and not r['in_zotero']
    os.makedirs(os.path.dirname(paths.local_pdf(pid)), exist_ok=True)
    io.open(paths.local_pdf(pid), 'wb').write(b'%PDF')
    os.makedirs(paths.parsed_dir(pid), exist_ok=True)
    io.open(paths.fulltext(pid), 'w').write('# T')
    r = catalog.record(pid)
    assert r['pdf'] and r['fulltext'] and not r['si']


def test_只有raw目录没有meta的也算在库里(env):
    """落了正本但登记失败（Crossref 不通）的文献不该从目录里消失。"""
    pid = paths.paper_id_from_doi(DOI)
    os.makedirs(paths.paper_raw_dir(pid))
    assert pid in catalog.ids()
    assert catalog.stats()['papers'] == 1


def test_临时区和非法目录名不算文献(env):
    os.makedirs(os.path.join(paths.RAW, '_incoming'))
    os.makedirs(os.path.join(paths.RAW, 'not a key'))
    assert catalog.ids() == []


def test_have_index与Zotero那份同形状_可直接并集(env):
    pid = paths.paper_id_from_doi(DOI)
    catalog.register(pid, doi=DOI, title='Room-Temperature Self-Healing Polymers')
    titles, dois = catalog.have_index()
    assert DOI in dois and 'roomtemperatureselfhealingpolymers' in titles


def test_同一DOI两个目录时优先Zotero编号(env):
    """老数据在 Zotero 编号那边（精读、抽取都在），别让 doi_ 目录把它顶掉。"""
    catalog.register(paths.paper_id_from_doi(DOI), doi=DOI)
    catalog.register('CCCC3333', doi=DOI)
    assert catalog.find(DOI) == 'CCCC3333'


def test_搜标题或DOI(env):
    catalog.register('DDDD4444', doi=DOI, title='Boronic ester vitrimer', journal='Macromolecules')
    assert [r['id'] for r in catalog.search('vitrimer')] == ['DDDD4444']
    assert [r['id'] for r in catalog.search('5b00210')] == ['DDDD4444']
    assert catalog.search('') == []


def test_by_doi缓存_落新文献后自动失效(tmp_path, monkeypatch):
    """进程内缓存以目录 mtime 为印章：register 新的一篇后再问必须看得到（2026-09-16）。"""
    import os, time
    from shared.kernel import catalog, paths
    for name in ('RAW', 'CURATED'):
        d = tmp_path / name.lower(); d.mkdir(); monkeypatch.setattr(paths, name, str(d))
    catalog._cache_clear()
    assert catalog.by_doi() == {}
    catalog.register('AAAA1111', doi='10.1/x')
    assert catalog.find('10.1/x') == 'AAAA1111'
    # 别的进程落了一篇（只建目录写文件，不经 register）→ 目录 mtime 变 → 缓存失效
    time.sleep(0.02)
    os.makedirs(str(tmp_path / 'curated' / 'BBBB2222'))
    open(str(tmp_path / 'curated' / 'BBBB2222' / 'meta.json'), 'w').write('{"doi": "10.1/y"}')
    assert catalog.find('10.1/y') == 'BBBB2222'


def test_level_of():
    from shared.kernel import catalog
    assert catalog.level_of({}) == 0
    assert catalog.level_of({'fulltext': True}) == 1
    assert catalog.level_of({'fulltext': True, 'pdf': True}) == 2
    assert catalog.level_of({'pdf': True, 'summary': True}) == 3
