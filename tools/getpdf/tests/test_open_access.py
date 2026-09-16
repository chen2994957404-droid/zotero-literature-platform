# -*- coding: utf-8 -*-
"""取正文前先问 Unpaywall（2026-09-16）：有合法开放版本就不敲出版商；没有 / 投稿稿 / 没配邮箱就照常走浏览器。全离线。"""
import os

from tools import getpdf


def _no_browser(monkeypatch):
    calls = []
    monkeypatch.setattr(getpdf.pdf_fetch, 'fetch', lambda doi, **kw: (calls.append(doi) or {'ok': False, 'reason': 'no_access'}))
    return calls


def test_有开放版本就直接存_不敲出版商(tmp_path, monkeypatch):
    from shared.adapters import unpaywall
    monkeypatch.setattr(unpaywall, 'fetch_pdf', lambda doi: (b'%PDF-1.4 fake', {'version': 'acceptedManuscript', 'host': 'repository', 'pdf_url': 'https://repo/x.pdf'}))
    calls = _no_browser(monkeypatch)
    r = getpdf.fetch_one('10.1/oa', where=str(tmp_path))
    assert r['ok'] and r['reason'] == 'oa' and os.path.getsize(r['path']) > 0
    assert calls == []                                   # 浏览器一次没动


def test_投稿稿不要_没有就走浏览器(tmp_path, monkeypatch):
    from shared.adapters import unpaywall
    monkeypatch.setattr(unpaywall, 'fetch_pdf', lambda doi: (b'%PDF-1.4 fake', {'version': 'submittedVersion', 'host': 'repository', 'pdf_url': 'u'}))
    calls = _no_browser(monkeypatch)
    r = getpdf.fetch_one('10.1/sub', where=str(tmp_path))
    assert not r['ok'] and calls == ['10.1/sub']


def test_没配邮箱_或查挂了_都不影响取件(tmp_path, monkeypatch):
    from shared.adapters import unpaywall
    monkeypatch.setattr(unpaywall, 'fetch_pdf', lambda doi: (None, None))
    calls = _no_browser(monkeypatch)
    getpdf.fetch_one('10.1/a', where=str(tmp_path))
    monkeypatch.setattr(unpaywall, 'fetch_pdf', lambda doi: (_ for _ in ()).throw(RuntimeError('boom')))
    getpdf.fetch_one('10.1/b', where=str(tmp_path))
    assert calls == ['10.1/a', '10.1/b']
