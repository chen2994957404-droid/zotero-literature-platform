# -*- coding: utf-8 -*-
"""shared.kernel.heartbeat —— 常驻服务的两种「我还好」信号。

**为什么需要它**（2026-08-27 从主力机日志里查出来的真问题）：

`zotero_watcher` 原来只有一个心跳，写在轮询循环的开头：

```python
while True:
    写心跳                    # ← 只在这里写
    for it in 待处理文献:
        process_item(it)      # ← 精读一篇：解析 + 9000 字生成 + 裁图 + 回写
    time.sleep(60)
```

**精读期间完全不写心跳**，而看门狗的规则是「300 秒没更新 = 卡死，杀掉重启」。
精读一篇远不止 5 分钟 —— 于是**只要有文献在精读，看门狗几乎必然把它杀掉**。

看门狗日志坐实了：一个月内重启约 20 次，绝大多数是 `心跳已 3xx 秒未更新`，
**刚过 300 阈值**。真的死机不会这么整齐地卡在阈值附近。
代价是被杀那篇已经花掉的 MineRU 和 DeepSeek 调用作废，下一轮重来再花一次，
而且会在库里留下半成品（那 4 篇「缺核心产物」的文献很可能就是这么来的）。

## 根子上：一个信号回答不了两个问题

看门狗真正想知道的是两件不同的事：

| 问题 | 信号 | 谁写 | 超时意味着 |
|---|---|---|---|
| 进程还活着吗？ | `<名>_heartbeat.txt` | **后台线程**，固定节奏 | 进程死了/冻住了 |
| 还在往前推进吗？ | `<名>_progress.txt` | 干完一件事时 | 活着但空转/卡在某个调用上 |

拆开之后：
- 精读跑一小时，后台线程照常报活 → **不会被误杀**
- 进程真死了，后台线程也停了 → 5 分钟内发现
- 活着但卡在一个永不返回的网络调用上 → 进度信号超时（阈值放宽到几十分钟）兜住

## 用法

```python
from shared.kernel import heartbeat

heartbeat.start('watcher')          # 常驻服务启动时调一次，起后台线程
...
heartbeat.progress('watcher')       # 每完成一件实事时调一次

# 看门狗那边
heartbeat.age('watcher', 'alive')      # 距上次「我还活着」多少秒；没有文件返回 None
heartbeat.age('watcher', 'progress')

# 批量作业（不常驻）：每做完一件 progress，结束时 done；面板 / 体检用 overview() 看谁卡住了
heartbeat.progress('journalwatch-backfill'); ...; heartbeat.done('journalwatch-backfill')
heartbeat.overview()   # → [{name, state: running/stuck/dead/done, note}]
```

设计上刻意做成**永不抛异常**：一个报活的机制自己把主程序搞崩，就本末倒置了。
"""
import os
import threading
import time

from shared.kernel import paths

# 后台线程写「我还活着」的间隔。取值远小于看门狗阈值（300s），
# 这样偶尔漏写一两次也不会被误判。
DEFAULT_EVERY = 30

ALIVE = 'alive'
PROGRESS = 'progress'
DONE = 'done'          # 批量作业（回填 / 取件 / 金标）跑完时写：面板据此把「没进展」和「做完了」分开

_threads = {}          # 名字 → 线程，防止重复启动
_lock = threading.Lock()


def path(name, kind=ALIVE):
    """信号文件的位置。`kind` 取 'alive' 或 'progress'。

    ⚠ `alive` 的文件名保持 `<名>_heartbeat.txt` 不变 ——
    看门狗一直在读这个名字，改名会让新旧版本在滚动升级时对不上。
    """
    suffix = 'heartbeat' if kind == ALIVE else kind
    return paths.runtime(f'{name}_{suffix}.txt')


def _write(name, kind):
    """写一个时间戳。失败就算了 —— 报活机制不该把主程序搞崩。"""
    try:
        p = path(name, kind)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(str(int(time.time())))
        return True
    except Exception:
        return False


def beat(name):
    """立刻写一次「我还活着」。一般不用手调，`start` 起的线程会自动写。"""
    return _write(name, ALIVE)


def progress(name):
    """记一次「有实质进展」。每完成一件实事时调用。"""
    return _write(name, PROGRESS)


def done(name):
    """批量作业正常结束时调一次。之后「进度没更新」就是正常的，不再算卡住。"""
    return _write(name, DONE)


# 「多久没进展算卡住」：常驻服务 45 分钟（一篇精读可能就要半小时）；批量作业 20 分钟
# （取件 / 回填一块 / 解析一篇都远短于此，超过就是卡在某个不返回的调用上 —— 2026-09-15 取件
# 卡半小时、Edge 死三小时没人知道，就是因为没有这个判断）。
STUCK_SERVICE = 2700
STUCK_JOB = 1200
FORGOTTEN = 7 * 86400   # 信号文件超过一周没动 = 这台机器早就不跑它了（编程端的旧文件），不报


def overview(now=None):
    """所有写过信号的名字 → 状态一览（给面板和体检用）。

    每项：{name, alive_age, progress_age, done_age, state, note}
    state ∈ running（在跑且有进展）/ stuck（该有进展却没有）/ dead（常驻服务不报活）/ done（作业做完）/ idle
    常驻服务 = 有 alive 文件的；批量作业 = 只有 progress 的。
    """
    now = now or time.time()
    d = os.path.dirname(paths.runtime('x'))
    names = set()
    try:
        for f in os.listdir(d):
            for suf in ('_heartbeat.txt', '_progress.txt', '_done.txt'):
                if f.endswith(suf):
                    names.add(f[:-len(suf)])
    except Exception:
        return []
    out = []
    for n in sorted(names):
        a, p, dn = age(n, ALIVE), age(n, PROGRESS), age(n, DONE)
        if min(x for x in (a, p, dn) if x is not None) > FORGOTTEN:
            continue                                        # 一周前的旧文件：不是卡住，是早就不跑了
        if a is not None:                                   # 常驻服务
            if a > 300:
                st, note = 'dead', f'已 {int(a // 60)} 分钟没报活'
            elif p is not None and p > STUCK_SERVICE:
                st, note = 'stuck', f'活着，但 {int(p // 60)} 分钟没有任何进展'
            else:
                st, note = 'running', f'进展 {int((p or 0) // 60)} 分钟前'
        elif p is None:
            continue
        elif dn is not None and dn <= p + 5:                # done 在 progress 之后（或同时）
            st, note = 'done', f'{int(dn // 60)} 分钟前做完'
        elif p > STUCK_JOB:
            st, note = 'stuck', f'{int(p // 60)} 分钟没进展，也没报做完 —— 多半卡住了'
        else:
            st, note = 'running', f'进展 {int(p // 60)} 分钟前'
        out.append({'name': n, 'alive_age': a, 'progress_age': p, 'done_age': dn, 'state': st, 'note': note})
    return out


def start(name, every=DEFAULT_EVERY):
    """起一个后台线程，固定节奏写「我还活着」。

    重复调用同一个名字不会起第二个线程（幂等）。
    线程是 daemon，主程序退出时跟着退出，不会吊住进程。
    """
    with _lock:
        t = _threads.get(name)
        if t is not None and t.is_alive():
            return t
        _write(name, ALIVE)          # 先写一次，别让看门狗在起步阶段就判死
        _write(name, PROGRESS)

        def _loop():
            while True:
                time.sleep(every)
                _write(name, ALIVE)

        t = threading.Thread(target=_loop, name=f'heartbeat:{name}', daemon=True)
        t.start()
        _threads[name] = t
        return t


def age(name, kind=ALIVE):
    """距上次写入过了多少秒。文件不存在或读不了返回 None。"""
    try:
        raw = open(path(name, kind), encoding='utf-8').read().strip()
        return time.time() - int(raw)
    except Exception:
        return None


def verdict(alive_age, progress_age, stale=300, no_progress=2700):
    """看门狗的判断：该不该重启，为什么。

    做成**纯函数**是为了能直接测 —— 判断逻辑不该只能靠「真让它卡一次」来验证。

    返回 `(要重启吗, 原因)`：

    - 报活信号没了或超时 → 进程死了/冻住了 → 重启
    - 报活正常但进度太久没动 → 活着在空转，或卡在一个永不返回的调用上 → 重启
    - 其余 → 不动。**正在精读所以进度没更新，但报活正常，属于这一类。**
    """
    if alive_age is None:
        return True, '报活信号缺失，watcher 可能没启动'
    if alive_age > stale:
        return True, f'已 {int(alive_age)}s 没报活（>{stale}）——进程可能死了或冻住了'
    if progress_age is not None and progress_age > no_progress:
        return True, (f'报活正常，但已 {int(progress_age)}s 没有任何进展'
                      f'（>{no_progress}）——可能卡在某个不返回的调用上')
    return False, ''
