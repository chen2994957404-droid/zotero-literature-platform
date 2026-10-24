# -*- coding: utf-8 -*-
"""单篇精读的两个前置步骤（2026-10-13 从打标签精读监听搬来，测试一并搬来）。全离线。"""
import io
import os

import pytest

from shared.kernel import catalog, paths
from host.app import runner as w

DOI = '10.1021/acs.macromol.6c00991'


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ('RAW', 'CURATED', 'STATE'):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(paths, name, str(d))
    catalog._cache_clear()
    return tmp_path


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
