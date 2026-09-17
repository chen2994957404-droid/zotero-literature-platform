# -*- coding: utf-8 -*-
"""看门狗的判断接线测试。

`shared.kernel.heartbeat.verdict` 的边界已在 `test_core_heartbeat.py` 测过；
这里测的是**看门狗有没有把它接对** —— 阈值传对了吗、两个信号读对了吗。

为什么值得单独测：接错的后果不是报错，而是**看门狗继续误杀正在干活的 watcher**，
表现和修之前一模一样，很难发现修复其实没生效。
"""
import os
import time

import pytest

from shared.kernel import heartbeat
from host.watcher import watchdog as _watchdog


@pytest.fixture
def wd(tmp_path, monkeypatch):
    """看门狗模块 + 把信号文件重定向到临时目录。

    `heartbeat.path()` 在**调用时**才问 paths.runtime，所以模块正常 import
    也照样被这个 monkeypatch 罩住。
    """
    monkeypatch.setattr(heartbeat.paths, 'runtime', lambda name, **kw: str(tmp_path / name))
    return _watchdog


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
    src = open(os.path.join(os.path.dirname(os.path.abspath(_watchdog.__file__)),
                            'service.py'), encoding='utf-8').read()
    assert f"heartbeat.start('{wd.BEACON}')" in src, (
        f'看门狗盯的是 {wd.BEACON!r}，但 watcher 没有用这个名字报活')
    assert f"heartbeat.progress('{wd.BEACON}')" in src


# ── 2026-09-17 起看门狗管三个进程 + 每日作业 ─────────────────────────────

def test_进程表里每个报活名都真有人在用(wd):
    """看门狗按 beacon 盯进程；进程那头必须真用同一个名字 heartbeat.start，否则永远「报活缺失」→ 每分钟重启一次。"""
    import importlib
    for svc in wd.SERVICES:
        mod = importlib.import_module(svc['module'] + ('.__main__' if svc['module'] == 'host.ingest' else ''))
        src = open(mod.__file__, encoding='utf-8', errors='replace').read()
        assert (f"heartbeat.start('{svc['beacon']}')" in src
                or f"heartbeat.start(BEACON)" in src and f"BEACON = '{svc['beacon']}'" in src), (
            f'看门狗盯的是 {svc["beacon"]!r}，但 {svc["module"]} 没有用这个名字报活')


def test_进程表的正则认不到看门狗自己(wd):
    """认模块路径不认单个词：`watcher` 一个词会把 host.watcher.watchdog 自己杀掉。"""
    import re
    me = 'python -m host.watcher.watchdog'
    for svc in wd.SERVICES:
        pat = svc['pat'].strip("'").replace(chr(92) * 2, chr(92))
        assert not re.search(pat, me), f'{svc["name"]} 的正则 {pat!r} 会匹配到看门狗自己'
        assert re.search(pat, f'python -m {svc["module"]} {" ".join(svc["args"])}')


class TestDailyDue:
    def _at(self, hhmm):
        import time
        y, m, d = 2026, 9, 17
        h, mi = map(int, hhmm.split(':'))
        return time.mktime((y, m, d, h, mi, 0, 0, 0, -1))

    def test_今天拉过就不再拉(self, wd):
        assert not wd.daily_due(self._at('03:00'), last_day='2026-09-17')

    def test_没到凌晨两点不拉(self, wd):
        assert not wd.daily_due(self._at('01:59'), last_day='2026-09-16')

    def test_过了两点且今天没拉过就拉(self, wd):
        assert wd.daily_due(self._at('02:00'), last_day='2026-09-16')
        assert wd.daily_due(self._at('15:00'), last_day='')      # 从没跑过：白天开机也补上

    def test_拉过之后印章落盘(self, wd, monkeypatch):
        monkeypatch.setattr(wd, 'spawn_module', lambda *a, **k: None)
        wd.launch_daily()
        assert not wd.daily_due(self._at('23:00'))
