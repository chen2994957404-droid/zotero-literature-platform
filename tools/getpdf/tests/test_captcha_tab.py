# -*- coding: utf-8 -*-
"""撞上人机验证的标签要留着、拉到最前面（2026-10-05）。

用户：「弹了人机验证的提示，打开浏览器却没看到」—— 取件标签是后台开的，撞上验证后又被关掉了，
人到浏览器前只剩首页。全离线：浏览器、标签都是替身。
"""
from shared.adapters import pdf_fetch


class FakePage:
    def __init__(self):
        self.closed = self.fronted = False
        self.url = 'https://example.org/verify'
        self.context = self

    @property
    def pages(self):
        return [self, self]

    def close(self):
        self.closed = True

    def bring_to_front(self):
        self.fronted = True

    def goto(self, *a, **k):
        pass


def _wire(monkeypatch, state):
    page = FakePage()
    monkeypatch.setattr(pdf_fetch, '_connect', lambda url=None: (None, None))
    monkeypatch.setattr(pdf_fetch, '_new_page', lambda b, c: page)
    monkeypatch.setattr(pdf_fetch, '_land', lambda *a, **k: state)
    return page


def test_撞上验证_标签留着并拉到最前(monkeypatch):
    page = _wire(monkeypatch, {'captcha': True, 'url': 'u', 'title': 't'})
    r = pdf_fetch.fetch('10.1/x')
    assert r['reason'] == 'captcha'
    assert page.fronted and not page.closed, '验证只有人能点：标签得留在人眼前'
    m, s = pdf_fetch.fetch_both('10.1/x')
    assert m['reason'] == 'captcha' and not page.closed


def test_没撞验证的标签照常关掉(monkeypatch):
    page = _wire(monkeypatch, {'captcha': False, 'url': 'u', 'title': 't', 'candidates': [], 'paywall': True})
    r = pdf_fetch.fetch('10.1/x')
    assert r['reason'] == 'no_access'
    assert page.closed and not page.fronted, '平时取件照旧后台、用完就关，不打扰人'
