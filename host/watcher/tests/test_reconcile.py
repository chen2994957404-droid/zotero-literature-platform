# -*- coding: utf-8 -*-
"""打标签的条目要按 DOI 认出证据库里已有的那篇；有范文的用推文当正文精读（2026-09-15）。

全离线：不碰 Zotero、不取图（范文里的图链接换成假替身）。
"""
import io
import json
import os

import pytest

from shared.kernel import catalog, paths
from host.watcher import service as w
from host import wechat_import

DOI = '10.1021/acs.macromol.6c00991'


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ('RAW', 'CURATED', 'STATE'):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(paths, name, str(d))
    from shared.kernel import jobs
    monkeypatch.setattr(paths, 'STATE', str(tmp_path / 'state'))
    monkeypatch.setattr(wechat_import, 'fetch_images', lambda article, log=print: {})
    catalog._cache_clear() if hasattr(catalog, '_cache_clear') else None
    return tmp_path


def test_按DOI认出已落地的同一篇(env):
    pid = paths.paper_id_from_doi(DOI)
    catalog.register(pid, doi=DOI, title='x')
    item = {'key': 'ABCD1234', 'data': {'DOI': DOI, 'title': 'x'}}
    assert w.paper_id_for(item) == pid
    assert catalog.read_meta(pid).get('zotero_key') == 'ABCD1234'      # Zotero 编号成了属性


def test_证据库没有就用Zotero编号(env):
    item = {'key': 'ABCD1234', 'data': {'DOI': '10.1000/new', 'title': 'y'}}
    assert w.paper_id_for(item) == 'ABCD1234'
    assert w.paper_id_for({'key': 'EFGH5678', 'data': {}}) == 'EFGH5678'   # 没 DOI 也不炸


def test_有范文就当正文精读_没范文不动(env):
    pid = paths.paper_id_from_doi(DOI)
    catalog.register(pid, doi=DOI, title='x')
    assert w.adopt_reference(pid, log=lambda *a: None) is False           # 没范文
    os.makedirs(os.path.dirname(paths.reference(pid)), exist_ok=True)
    io.open(paths.reference(pid), 'w', encoding='utf-8').write(
        '# 【AFM】范文\n\n来源: 高分子学人 · 2026-09-01 · a.md\nDOI: %s\n\n---\n\n近期，A B 报道了。\n\n'
        '![](https://mmbiz.qpic.cn/x/1.jpg)\n\n总之，好。\n' % DOI)
    assert w.adopt_reference(pid, log=lambda *a: None) is True
    html = io.open(paths.summary(pid), encoding='utf-8').read()
    assert '近期，A B 报道了' in html and '总之，好' in html
    assert w.adopt_reference(pid, log=lambda *a: None) is False           # 已有精读不重装


def test_范文读回article():
    import tempfile
    p = os.path.join(tempfile.gettempdir(), 'ref_test.md')
    io.open(p, 'w', encoding='utf-8').write('# T\n\n来源: 高分子学人 · 2026-09-01 · a.md\nDOI: 10.1/x\n\n---\n\n段一\n\n![](http://i/1.jpg)\n\n段二\n')
    a = wechat_import.article_from_reference(p)
    assert a['title'] == 'T' and a['doi'] == '10.1/x' and a['pubdate'] == '2026-09-01'
    assert [b['kind'] for b in a['blocks']] == ['p', 'img', 'p']
