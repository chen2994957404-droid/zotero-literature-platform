# -*- coding: utf-8 -*-
"""「查产物缺口」的测试 —— 用临时目录造出各种半成品，验证它判得对不对。

编程端 library 是空的，所以这里**造假数据来测**：
真实的半成品在主力机上，而判断逻辑必须在这边就能验证，
否则又变成「只能上线了才知道对不对」。
"""
import importlib.util
import os

import pytest

from core import paths

MODULE = os.path.join(paths.ROOT, '平台管理', '查产物缺口.py')


@pytest.fixture
def gaps(tmp_path, monkeypatch):
    """加载脚本，并把 library 指到临时目录。"""
    lib = tmp_path / 'library'
    lib.mkdir()
    monkeypatch.setattr(paths, 'LIBRARY', str(lib))
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


ALL = ['parsed/full.md', 'parsed/layout.json', 'meta.json', 'summary.html']


class TestInspect:
    def test_产物齐全时不算缺(self, gaps, tmp_path):
        make(tmp_path / 'library', 'AAAAAAAA', ALL)
        missing, present, _size = gaps.inspect('AAAAAAAA')
        assert missing == [] and len(present) == 4

    def test_能认出缺哪些(self, gaps, tmp_path):
        make(tmp_path / 'library', 'BBBBBBBB', ['parsed/full.md', 'meta.json'])
        missing, present, _ = gaps.inspect('BBBBBBBB')
        assert 'summary' in missing and 'fulltext' in present

    def test_空目录算全缺(self, gaps, tmp_path):
        os.makedirs(str(tmp_path / 'library' / 'CCCCCCCC'))
        missing, present, size = gaps.inspect('CCCCCCCC')
        assert len(missing) == 4 and present == [] and size == 0


class TestDiagnose:
    def test_解析就没成(self, gaps):
        stage, advice = gaps.diagnose(missing=['fulltext', 'summary'], present=[])
        assert '解析' in stage and '待处理' in advice

    def test_精读没做完(self, gaps):
        """**这是被误杀最典型的形态**：正文在了，精读报告没出来。

        建议里必须点出「解析结果还在，不会重复花 MineRU 的钱」——
        用户最关心的就是重做要不要再花一次。
        """
        stage, advice = gaps.diagnose(missing=['summary'],
                                      present=['fulltext', 'layout', 'meta'])
        assert '精读没做完' in stage
        assert 'MineRU' in advice

    def test_完整时不给建议(self, gaps):
        assert gaps.diagnose(missing=[], present=['fulltext'])[0] == '完整'


def test_只读不改任何东西(gaps, tmp_path):
    """这个脚本会在主力机上跑，**绝不能动数据**。"""
    lib = tmp_path / 'library'
    d = make(lib, 'DDDDDDDD', ['parsed/full.md'])
    before = sorted(os.walk(str(lib)))
    gaps.inspect('DDDDDDDD')
    gaps.diagnose(*gaps.inspect('DDDDDDDD')[:2])
    assert sorted(os.walk(str(lib))) == before
    assert os.path.isfile(os.path.join(d, 'parsed', 'full.md'))
