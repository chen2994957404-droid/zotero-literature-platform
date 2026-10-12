# -*- coding: utf-8 -*-
"""精读计划（tools.deepread.plan）—— 文献库应用的按钮靠它说「点了会做什么」。全离线、临时目录。"""
import io
import os

import pytest

from shared.kernel import paths
import tools.deepread as dr


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ('RAW', 'CURATED', 'STATE'):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(paths, name, str(d))
    return 'doi_10.1-x'


def _touch(p):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    io.open(p, 'w').write('x')


def test_什么都没有(env):
    assert dr.plan(env)['action'] == 'nothing'


def test_只有正文(env):
    _touch(paths.local_pdf(env))
    assert dr.plan(env)['action'] == 'main'


def test_正文和SI都有(env):
    _touch(paths.local_pdf(env)); _touch(paths.local_si(env))
    assert dr.plan(env)['action'] == 'full'


def test_正文精读过_只补SI(env):
    _touch(paths.local_pdf(env)); _touch(paths.local_si(env)); _touch(paths.summary(env))
    assert dr.plan(env)['action'] == 'si_only'


def test_都精读过了(env):
    _touch(paths.local_pdf(env)); _touch(paths.local_si(env)); _touch(paths.summary(env)); _touch(paths.si_summary(env))
    p = dr.plan(env)
    assert p['action'] == 'done' and not p['can']
