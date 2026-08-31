# -*- coding: utf-8 -*-
"""watcher 轮询判据的离线测试 —— 「这一篇现在该不该处理」。

这条判据错了会有两种失败，方向相反、代价都高：
  · 太保守 → **用户打了标签却毫无反应**（2026-08-28 真实发生，一小时零动静，
    日志里连一行「发现」都没有 —— 因为原来是「处理过一次就永远跳过」）
  · 太激进 → 卡住的条目每 60 秒重跑一次，烧 API 额度

所以它值得单独有测试。函数是纯的（不联网、不碰文件），秒级可验。
"""
import importlib.util
import os
import sys

import pytest

from shared.kernel import paths


def _load():
    """watcher 在中文目录下、不是包，只能按路径加载。"""
    f = os.path.join(paths.ROOT, '文献精读', 'zotero_watcher.py')
    spec = importlib.util.spec_from_file_location('_watcher_for_test', f)
    m = importlib.util.module_from_spec(spec)
    sys.modules['_watcher_for_test'] = m
    spec.loader.exec_module(m)
    return m


w = _load()
KEY = 'ABCD1234'
T0 = 1_000_000.0


def test_没见过的一定处理():
    assert w.should_process(KEY, 10, {}, T0) is True


def test_刚处理完且条目没变就不重复处理():
    """防的是「回写失败 → 标签还挂着 → 每 60 秒重跑一次烧钱」。"""
    seen = {KEY: (10, T0)}
    assert w.should_process(KEY, 10, seen, T0 + 60) is False


def test_用户重新打标签就必须处理():
    """**这条是这次 bug 的复现**：先精读正文，后来补了 SI 再打一次「待处理」。

    改标签会让 Zotero 条目的 version 变化 —— 这就是「用户明确要求」的信号。
    """
    seen = {KEY: (10, T0)}
    assert w.should_process(KEY, 11, seen, T0 + 60) is True


def test_超过重试间隔可以再试一次():
    """给「上次没做完」一个自愈机会，而不是非等 watcher 重启不可。"""
    seen = {KEY: (10, T0)}
    assert w.should_process(KEY, 10, seen, T0 + w.RETRY_AFTER - 1) is False
    assert w.should_process(KEY, 10, seen, T0 + w.RETRY_AFTER) is True


def test_重试间隔不能短到会烧钱():
    """真要卡住了，一小时最多重试两次 —— 幂等保证每次几乎不花钱，但别刷屏。"""
    assert w.RETRY_AFTER >= 600


def test_不同文献互不影响():
    seen = {KEY: (10, T0)}
    assert w.should_process('ZZZZ9999', 1, seen, T0 + 1) is True


@pytest.mark.parametrize('ver', [None, 0, ''])
def test_取不到version时按变化处理(ver):
    """宁可多跑一次（幂等、几乎不花钱），也不要让用户打了标签没反应。"""
    seen = {KEY: (10, T0)}
    assert w.should_process(KEY, ver, seen, T0 + 1) is True
