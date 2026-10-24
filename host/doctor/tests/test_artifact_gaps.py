# -*- coding: utf-8 -*-
"""「查产物缺口」的测试 —— 用临时目录造出各种半成品，验证它判得对不对。

编程端 library 是空的，所以这里**造假数据来测**：
真实的半成品在主力机上，而判断逻辑必须在这边就能验证，
否则又变成「只能上线了才知道对不对」。
"""
import importlib.util
import os

import pytest

from shared.kernel import paths

MODULE = os.path.join(paths.ROOT, 'host', 'doctor', 'artifact_gaps.py')


@pytest.fixture
def gaps(tmp_path, monkeypatch):
    """加载脚本，并把两个数据层都指到临时目录。

    R6 起一篇文献跨两层：解析产物在 raw、目录卡在 curated。
    这里把 raw 也指过去，`make()` 造的 parsed/full.md 才落得进沙箱。
    """
    lib = tmp_path / 'curated'
    lib.mkdir()
    monkeypatch.setattr(paths, 'CURATED', str(lib))
    monkeypatch.setattr(paths, 'RAW', str(lib))
    spec = importlib.util.spec_from_file_location('gaps_under_test', MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def make(lib, key, files):
    d = os.path.join(str(lib), key)
    for rel in files:
        p = os.path.join(d, rel.replace('/', os.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'w', encoding='utf-8').write('x' * 10)
    return d


ALL = ['parsed/full.md', 'parsed/layout.json', 'meta.json']


class TestInspect:
    def test_产物齐全时不算缺(self, gaps, tmp_path):
        make(tmp_path / 'curated', 'AAAAAAAA', ALL)
        missing, present, _size = gaps.inspect('AAAAAAAA')
        assert missing == [] and len(present) == 3

    def test_能认出缺哪些(self, gaps, tmp_path):
        make(tmp_path / 'curated', 'BBBBBBBB', ['parsed/full.md', 'parsed/layout.json'])
        missing, present, _ = gaps.inspect('BBBBBBBB')
        assert missing == ['meta'] and 'fulltext' in present

    def test_空目录算全缺(self, gaps, tmp_path):
        os.makedirs(str(tmp_path / 'curated' / 'CCCCCCCC'))
        missing, present, size = gaps.inspect('CCCCCCCC')
        assert len(missing) == 3 and present == [] and size == 0


class TestDiagnose:
    def test_没解析_建议跑落地流水线且说明不花大模型钱(self, gaps):
        stage, advice = gaps.diagnose(missing=['fulltext', 'layout'], present=['meta'])
        assert '解析' in stage and 'host.ingest' in advice and '不花大模型' in advice

    def test_只缺元数据(self, gaps):
        stage, advice = gaps.diagnose(missing=['meta'], present=['fulltext', 'layout'])
        assert '元数据' in stage and '不花钱' in advice

    def test_完整时不给建议(self, gaps):
        assert gaps.diagnose(missing=[], present=['fulltext'])[0] == '完整'


def test_只读不改任何东西(gaps, tmp_path):
    """这个脚本会在主力机上跑，**绝不能动数据**。"""
    lib = tmp_path / 'curated'
    d = make(lib, 'DDDDDDDD', ['parsed/full.md'])
    before = sorted(os.walk(str(lib)))
    gaps.inspect('DDDDDDDD')
    gaps.diagnose(*gaps.inspect('DDDDDDDD')[:2])
    assert sorted(os.walk(str(lib))) == before
    assert os.path.isfile(os.path.join(d, 'parsed', 'full.md'))
