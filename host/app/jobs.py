# -*- coding: utf-8 -*-
"""host.app.jobs · 文献库应用发起的作业：排队、一次跑一个、记结果（2026-10-12 起，目前只有单篇精读）。

为什么不在请求里直接跑：一篇精读要几分钟、要花钱，HTTP 请求等不了；
也不另起常驻服务：有人点了才拉起一个跑队列的进程（`runner`），队列空了它自己退出。
同一时刻只许一个跑队列的进程（`proc_lock`），所以一篇一篇来。

队列存在 `paths.app_jobs_db()`（SQLite：应用进程写、跑队列的进程改，两边并发靠它的锁）。

| 函数 | 干什么 |
|---|---|
| `enqueue(pid, kind='deepread')` | 排一个；同一篇已在排队 / 正在跑就不重复排 |
| `recent(n=20)` / `of(pid)` | 最近的作业 / 某篇最近一次 |
| `next_queued()` / `mark(...)` | 跑队列的进程用 |
| `ensure_runner()` | 没有跑队列的进程就拉起一个 |
"""
import os
import sqlite3
import sys
import time

from shared.kernel import paths

RUNNER_LOCK = 'app_jobs_runner'


def _con():
    os.makedirs(os.path.dirname(paths.app_jobs_db()), exist_ok=True)
    con = sqlite3.connect(paths.app_jobs_db(), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('create table if not exists jobs (id integer primary key autoincrement, pid text, kind text, '
                'state text, note text, t_queued real, t_start real, t_end real)')
    return con


def enqueue(pid, kind='deepread', note=''):
    with _con() as con:
        row = con.execute("select * from jobs where pid=? and kind=? and state in ('queued','running') "
                          'order by id desc limit 1', (pid, kind)).fetchone()
        if row:
            return dict(row), False
        cur = con.execute('insert into jobs (pid, kind, state, note, t_queued) values (?,?,?,?,?)',
                          (pid, kind, 'queued', note, time.time()))
        return dict(con.execute('select * from jobs where id=?', (cur.lastrowid,)).fetchone()), True


def recent(n=20):
    with _con() as con:
        return [dict(r) for r in con.execute('select * from jobs order by id desc limit ?', (n,))]


def of(pid, kind='deepread'):
    with _con() as con:
        r = con.execute('select * from jobs where pid=? and kind=? order by id desc limit 1', (pid, kind)).fetchone()
        return dict(r) if r else None


def next_queued():
    with _con() as con:
        r = con.execute("select * from jobs where state='queued' order by id limit 1").fetchone()
        return dict(r) if r else None


def mark(job_id, state, note=None):
    with _con() as con:
        if state == 'running':
            con.execute('update jobs set state=?, t_start=? where id=?', (state, time.time(), job_id))
        else:
            con.execute('update jobs set state=?, note=coalesce(?, note), t_end=? where id=?',
                        (state, note, time.time(), job_id))


def ensure_runner():
    """没有跑队列的进程就拉起一个（不等它）。返回是否新拉起了。"""
    from shared.kernel import proc_lock, subproc
    if proc_lock.holder(RUNNER_LOCK):
        return False
    subproc.spawn([sys.executable, '-m', 'host.app.runner'])
    return True
