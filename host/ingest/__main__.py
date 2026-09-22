# -*- coding: utf-8 -*-
"""python -m host.ingest [--limit N] [--不向量化] [--loop] —— 把证据库里积压的免费三步做完。

--loop：常驻。每 60 秒扫一次积压、做完、再睡 —— 这是落地流水线自己的进程（2026-09-17 起），
由看门狗 `host.watcher.watchdog` 拉起，跟精读监听互不拖累。
"""
import os, sys, time
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.kernel import heartbeat, role
from shared.kernel.cli import flag, opt, wants_help
from host import ingest

BEACON = 'ingest'        # 看门狗按这个名字盯它（host/watcher/watchdog.py 的 SERVICES）
EVERY = 60               # 常驻时两轮之间睡多久
PER_ROUND = 10           # 一轮最多做几篇（一篇解析一两分钟，别让一轮长到看门狗以为它卡了）
VECTOR_EVERY = 10        # 每几轮查一次向量化积压（要开向量库）
BACKOFF = 600            # 一轮全失败（服务没起来）时退避多久


def _report(c, say=print):
    say(f'做完：解析 {c["parsed"]} 篇 · SI {c["si_parsed"]} 篇 · 骨架 {c["outlined"]} 篇 · '
          f'向量化 {c["vectorized"]} 篇 · 单元库 {c.get("units", 0)} 篇 · 画像 {c.get("profile", 0)} 篇 · 失败 {c["failed"]} 篇')
    bad = ingest.failures()
    if bad:
        say('等重试的（一天后再试）：')
        for pid, step, err in bad:
            say(f'  {pid}  {step}  {err}')


def loop():
    """常驻：单实例锁在 run_backlog 里（抢不到就这轮让开），报活在这里。"""
    from shared.kernel.proc_lock import single_instance, holder
    if not single_instance('ingest_loop'):
        ingest.log(f'已有一份落地流水线常驻在跑（PID={holder("ingest_loop")}），本次退出')
        return 0
    heartbeat.start(BEACON)
    say = ingest.log          # 常驻是 pythonw 无窗口跑的，print 会被丢掉 —— 走日志文件（踩坑 #33）
    say(f'落地流水线常驻启动：每 {EVERY} 秒扫一次积压，一轮最多 {PER_ROUND} 篇')
    n = 0
    while True:
        # 解析积压（有正本没解析）查起来是毫秒级，每轮都查；向量化积压要开向量库（一两秒），
        # 每 10 轮查一次就够 —— 刚解析完的那篇最多晚 10 分钟入向量库。
        heavy = (n % VECTOR_EVERY == 0)
        n += 1
        sleep = EVERY
        try:
            if heavy or ingest.backlog():
                c = ingest.run_backlog(limit=PER_ROUND, say=say, with_vectors=heavy)
                if any(c.values()):
                    _report(c, say)
                    # 这轮只有失败没有成功（多半是 MineRU / Ollama 没起来）：退避 10 分钟，
                    # 别每分钟敲一次、每分钟写一行日志
                    if c['failed'] and not any(v for k, v in c.items() if k != 'failed'):
                        sleep = BACKOFF
        except Exception as e:
            say(f'[落地流水线失败] {type(e).__name__}: {e}')
            sleep = BACKOFF
        # 扫完一轮就是进展 —— 没积压时也要写，否则看门狗 45 分钟后会把闲着的它当「卡住」重启
        heartbeat.progress(BEACON)
        time.sleep(sleep)


def main():
    if wants_help():
        print(__doc__)
        return 0
    # 会花 MineRU 额度、写 data/raw —— 编程端默认拦住（测试角色放行）
    role.require_prod('落地流水线：解析 + 骨架 + 向量化（花 MineRU 额度）', force=flag('--force'))
    if flag('--loop'):
        return loop()
    c = ingest.run_backlog(limit=opt('--limit'), with_vectors=not flag('--不向量化'))
    _report(c)
    return 0


if __name__ == '__main__':
    from shared.kernel import errors as _err
    try:
        sys.exit(main())
    except _err.WrongMachineError as _e:
        print(str(_e))
        sys.exit(2)
