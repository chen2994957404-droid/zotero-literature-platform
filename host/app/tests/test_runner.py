# -*- coding: utf-8 -*-
"""单篇精读的两个前置步骤（2026-10-13 从打标签精读监听搬来，测试一并搬来）。全离线。"""
import io
import os

import pytest

from shared.kernel import catalog, paths
from host import wechat_import
from host.app import runner as w

DOI = '10.1021/acs.macromol.6c00991'


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ('RAW', 'CURATED', 'STATE'):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(paths, name, str(d))
    monkeypatch.setattr(wechat_import, 'fetch_images', lambda article, log=print: {})
    catalog._cache_clear()
    return tmp_path


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


def test_精读前补SI_记过没有的不再去取_浏览器没开不拖累(env, monkeypatch):
    pid = paths.paper_id_from_doi(DOI)
    catalog.register(pid, doi=DOI, title='x')
    calls = []
    from tools import getpdf

    def fake_land(doi, pdf_path=None, **kw):
        calls.append(doi)
        return {'si': '', 'note': '正文有；没有 SI（出版商页面确认）'}
    monkeypatch.setattr(getpdf, 'land', fake_land)
    quiet = lambda *a: None
    assert w.try_fetch_si(pid, 'main.pdf', log=quiet) is False and calls == [catalog.norm_doi(DOI)]
    catalog.mark_si_none(pid)                                            # 目录记了「没有」→ 第二次直接不去
    assert w.try_fetch_si(pid, 'main.pdf', log=quiet) is False and len(calls) == 1
    catalog.register(pid, overwrite=True, si_status=catalog.SI_UNKNOWN)

    def boom(doi, pdf_path=None, **kw):
        raise RuntimeError('浏览器没开')
    monkeypatch.setattr(getpdf, 'land', boom)
    assert w.try_fetch_si(pid, 'main.pdf', log=quiet) is False             # 浏览器没开 → 不抛
    catalog.register('doi_10.9-nodoi', title='没 DOI')
    assert w.try_fetch_si('doi_10.9-nodoi', 'main.pdf', log=quiet) is False
