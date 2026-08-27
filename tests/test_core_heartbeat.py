# -*- coding: utf-8 -*-
"""core.heartbeat 的单元测试。

**这些测试挡的是真金白银**：原来的单心跳让看门狗在精读中途把 watcher 杀掉，
被杀那篇已经花掉的 MineRU / DeepSeek 调用作废，下一轮重来再花一次
（主力机一个月被误杀约 20 次）。

所以重点测两件事：
① 后台线程在「主线程正忙」时照样报活 —— 不会被误杀
② `verdict` 的判断边界 —— 什么该重启、什么不该
"""
import time

import pytest

from core import heartbeat


@pytest.fixture(autouse=True)
def 用临时目录(tmp_path, monkeypatch):
    """信号文件写进 pytest 的临时目录，绝不碰真实运行目录。"""
    monkeypatch.setattr(heartbeat.paths, 'runtime',
                        lambda name, **kw: str(tmp_path / name))
    heartbeat._threads.clear()
    yield
    heartbeat._threads.clear()


class TestVerdict:
    """看门狗的判断逻辑。做成纯函数就是为了能这样直接测。"""

    def test_报活缺失要重启(self):
        restart, why = heartbeat.verdict(None, None)
        assert restart and '缺失' in why

    def test_报活超时要重启(self):
        restart, why = heartbeat.verdict(400, 10)
        assert restart and '没报活' in why

    def test_正在精读时不许重启(self):
        """核心用例：报活正常、进度停了 20 分钟（正在精读一篇）——**不能杀**。

        这正是原来那个 bug：进度没更新就被当成卡死。
        """
        restart, _ = heartbeat.verdict(alive_age=12, progress_age=1200)
        assert restart is False

    def test_活着但长期没进展要重启(self):
        """卡在一个永不返回的网络调用上：线程还在报活，但什么也没推进。"""
        restart, why = heartbeat.verdict(alive_age=12, progress_age=4000)
        assert restart and '没有任何进展' in why

    def test_一切正常不重启(self):
        assert heartbeat.verdict(5, 30) == (False, '')

    def test_没有进度文件时只看报活(self):
        """老版本 watcher 不写进度文件；不能因为「没有进度」就把它杀了。"""
        assert heartbeat.verdict(alive_age=10, progress_age=None)[0] is False

    @pytest.mark.parametrize('alive_age,expect', [(299, False), (301, True)])
    def test_报活阈值边界(self, alive_age, expect):
        assert heartbeat.verdict(alive_age, 10)[0] is expect

    @pytest.mark.parametrize('prog,expect', [(2699, False), (2701, True)])
    def test_进度阈值边界(self, prog, expect):
        assert heartbeat.verdict(10, prog)[0] is expect


class TestFiles:
    def test_报活文件名保持不变(self):
        """看门狗一直读 `<名>_heartbeat.txt`，改名会让滚动升级时新旧版本对不上。"""
        assert heartbeat.path('watcher', heartbeat.ALIVE).endswith('watcher_heartbeat.txt')
        assert heartbeat.path('watcher', heartbeat.PROGRESS).endswith('watcher_progress.txt')

    def test_beat写出可读的时间戳(self):
        assert heartbeat.beat('w') is True
        assert 0 <= heartbeat.age('w', heartbeat.ALIVE) < 5

    def test_progress单独计龄(self):
        heartbeat.progress('w')
        assert 0 <= heartbeat.age('w', heartbeat.PROGRESS) < 5

    def test_文件不存在时年龄是None(self):
        assert heartbeat.age('从来没写过的名字') is None

    def test_文件内容坏了也不抛异常(self, tmp_path):
        p = heartbeat.path('w')
        open(p, 'w', encoding='utf-8').write('这不是时间戳')
        assert heartbeat.age('w') is None


class TestBackgroundThread:
    def test_start会立刻写一次两种信号(self):
        """别让看门狗在服务刚起步、还没干活时就判死。"""
        heartbeat.start('w', every=60)
        assert heartbeat.age('w', heartbeat.ALIVE) is not None
        assert heartbeat.age('w', heartbeat.PROGRESS) is not None

    def test_主线程忙着时后台仍在报活(self):
        """**这条就是那个 bug 的回归测试。**

        模拟「精读一篇很久」：主线程完全不调 progress，只是在忙。
        后台线程必须继续报活，否则看门狗就会把正在干活的进程杀掉。

        比较的是**时间戳本身**而不是 `age` —— 时间戳按整秒存
        （旧看门狗用 `int()` 解析，写浮点会让它直接崩），
        用 age 在秒级以下量不准。
        """
        def stamp(kind):
            return int(open(heartbeat.path('w', kind), encoding='utf-8').read().strip())

        heartbeat.start('w', every=0.2)
        alive_before, prog_before = stamp(heartbeat.ALIVE), stamp(heartbeat.PROGRESS)
        time.sleep(2.5)                      # 假装在精读，期间一次 progress 都不调
        alive_after, prog_after = stamp(heartbeat.ALIVE), stamp(heartbeat.PROGRESS)

        assert alive_after > alive_before, '后台线程没在报活 —— 正在干活的进程会被误杀'
        assert prog_after == prog_before, '这条测的就是「忙但没进展」，进度不该动'

        # 而按判断规则，这种情况绝不能重启
        restart, why = heartbeat.verdict(heartbeat.age('w', heartbeat.ALIVE),
                                         heartbeat.age('w', heartbeat.PROGRESS))
        assert restart is False, f'正在精读却被判要重启：{why}'


    def test_重复start不会起第二个线程(self):
        t1 = heartbeat.start('w', every=60)
        t2 = heartbeat.start('w', every=60)
        assert t1 is t2

    def test_线程是daemon不会吊住进程(self):
        t = heartbeat.start('w', every=60)
        assert t.daemon is True
