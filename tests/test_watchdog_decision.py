# -*- coding: utf-8 -*-
"""看门狗的判断接线测试。

`shared.kernel.heartbeat.verdict` 的边界已在 `test_core_heartbeat.py` 测过；
这里测的是**看门狗有没有把它接对** —— 阈值传对了吗、两个信号读对了吗。

为什么值得单独测：接错的后果不是报错，而是**看门狗继续误杀正在干活的 watcher**，
表现和修之前一模一样，很难发现修复其实没生效。
"""
import importlib.util
import os
import time

import pytest

from shared.kernel import heartbeat, paths

WATCHDOG_PY = os.path.join(paths.ROOT, '文献精读', 'watchdog.py')


@pytest.fixture
def wd(tmp_path, monkeypatch):
    """加载看门狗模块，并把信号文件重定向到临时目录。"""
    monkeypatch.setattr(heartbeat.paths, 'runtime', lambda name, **kw: str(tmp_path / name))
    spec = importlib.util.spec_from_file_location('watchdog_under_test', WATCHDOG_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _stamp(name, kind, seconds_ago):
    open(heartbeat.path(name, kind), 'w', encoding='utf-8').write(
        str(int(time.time()) - seconds_ago))


class TestThresholds:
    def test_无进展阈值必须远大于一篇精读的耗时(self, wd):
        """这个阈值一旦订得太小，就等于把刚修好的 bug 原样装回去。

        精读一篇 = MineRU 解析 + 9000 字生成 + 裁图 + 回写，十几分钟是常态。
        """
        assert wd.NO_PROGRESS >= 1800, '无进展阈值太小，会重新开始误杀正在精读的 watcher'
        assert wd.NO_PROGRESS > wd.STALE * 3

    def test_报活阈值远大于后台线程的写入间隔(self, wd):
        """漏写一两次不该被判死。"""
        assert wd.STALE >= heartbeat.DEFAULT_EVERY * 5


class TestWiring:
    def test_正在精读时不重启(self, wd):
        """**这条就是那个 bug 的回归测试。**

        后台线程刚报过活，但进度停在 20 分钟前（正在精读一篇）—— 绝不能杀。
        """
        _stamp(wd.BEACON, heartbeat.ALIVE, 5)
        _stamp(wd.BEACON, heartbeat.PROGRESS, 1200)
        alive, prog = wd.ages()
        need, why = heartbeat.verdict(alive, prog, stale=wd.STALE,
                                      no_progress=wd.NO_PROGRESS)
        assert need is False, f'正在精读却被判要重启：{why}'

    def test_进程死了要重启(self, wd):
        _stamp(wd.BEACON, heartbeat.ALIVE, 400)
        _stamp(wd.BEACON, heartbeat.PROGRESS, 400)
        need, why = heartbeat.verdict(*wd.ages(), stale=wd.STALE,
                                      no_progress=wd.NO_PROGRESS)
        assert need and '没报活' in why

    def test_活着但长期空转要重启(self, wd):
        _stamp(wd.BEACON, heartbeat.ALIVE, 5)
        _stamp(wd.BEACON, heartbeat.PROGRESS, wd.NO_PROGRESS + 100)
        need, why = heartbeat.verdict(*wd.ages(), stale=wd.STALE,
                                      no_progress=wd.NO_PROGRESS)
        assert need and '没有任何进展' in why

    def test_信号文件都没有时要重启(self, wd):
        need, why = heartbeat.verdict(*wd.ages(), stale=wd.STALE,
                                      no_progress=wd.NO_PROGRESS)
        assert need and '缺失' in why

    def test_ages读的是两个不同的信号(self, wd):
        _stamp(wd.BEACON, heartbeat.ALIVE, 10)
        _stamp(wd.BEACON, heartbeat.PROGRESS, 900)
        alive, prog = wd.ages()
        assert 5 < alive < 60 and 800 < prog < 1000


def test_看门狗盯的名字和watcher报活的名字一致(wd):
    """两边名字对不上，看门狗就会永远读到「信号缺失」→ 无限重启。

    这种错不会报错，只会表现为「服务一直在重启」。
    """
    src = open(os.path.join(paths.ROOT, '文献精读', 'zotero_watcher.py'),
               encoding='utf-8').read()
    assert f"heartbeat.start('{wd.BEACON}')" in src, (
        f'看门狗盯的是 {wd.BEACON!r}，但 watcher 没有用这个名字报活')
    assert f"heartbeat.progress('{wd.BEACON}')" in src
