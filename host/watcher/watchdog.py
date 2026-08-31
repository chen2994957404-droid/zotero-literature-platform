# -*- coding: utf-8 -*-
"""watcher 看门狗：watcher 真死了就重启它 —— **但绝不打断正在干活的它**。

看两个信号（都由 `shared.kernel.heartbeat` 维护，那里有完整说明）：

    watcher_heartbeat.txt   后台线程固定节奏写   → 进程还活着吗
    watcher_progress.txt    每完成一件实事时写   → 还在往前推进吗

**为什么要两个**（2026-08-27 从主力机日志查出来的真问题）：
原来只有一个心跳，写在轮询循环开头，精读期间根本不写。
而精读一篇远不止 5 分钟 —— 于是看门狗每次都把**正在干活的 watcher 杀掉**，
一个月误杀约 20 次，每次都白花一份 MineRU + DeepSeek，还在库里留下半成品。

拆开之后：精读跑一小时也不会被误杀（后台仍在报活）；
进程真死了 5 分钟内发现；活着但卡在某个不返回的调用上，由进度阈值兜底。

用法: python -m host.watcher.watchdog    # 前台常驻；日常由任务计划自启
"""
import os, sys, time, subprocess

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from shared.kernel import heartbeat, role
from shared.kernel.cli import flag
from shared.kernel.paths import ROOT as _ROOT

from shared.kernel import subproc as _sp   # 统一走静默子进程调用，避免弹窗

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = _ROOT
WATCHER = os.path.join(SCRIPT_DIR, 'service.py')
BEACON = 'watcher'          # shared.kernel.heartbeat 里的名字

# 「哪些进程是 watcher」的唯一判据（见 find_watcher_pids 的说明）。
# PowerShell 单引号串里反斜杠是字面量，所以这一串原样就是正则。
WATCHER_PAT = "'watcher[\\\\./]service'"

CHECK = 60          # 每 60 秒查一次
STALE = 300         # 超 300 秒没报活 = 进程死了/冻住了。后台线程每 30 秒写一次，很宽容
NO_PROGRESS = 2700  # 报活正常但 45 分钟毫无进展 = 卡在某个不返回的调用上。
                    # 这个阈值必须**大于最慢一篇精读的耗时**，否则又变回误杀
GRACE = 180         # 重启后给 watcher 的启动宽限期，期间不判死


from shared.kernel.log import get_logger
log = get_logger('watchdog')   # 统一日志：时间戳 + 落盘 + 自动轮转


def ages():
    """(距上次报活多少秒, 距上次有进展多少秒)。读不到就是 None。"""
    return (heartbeat.age(BEACON, heartbeat.ALIVE),
            heartbeat.age(BEACON, heartbeat.PROGRESS))


def find_watcher_pids():
    """找正在跑的 watcher 进程（Windows）。

    走 subproc 积木：本函数每 60 秒被调一次，裸调 wmic 会不停弹控制台窗口（踩坑 #31）。
    wmic 在新版 Windows 已弃用，改用 PowerShell 的 CIM 查询，更可靠。

    ⚠ **认模块路径，不认单个词**（踩坑 #81 的第三次复发预防）。这里搬过两次家：
    `文献精读/zotero_watcher.py` → `tools/deepread/watcher.py` → `host/watcher/service.py`。
    每搬一次，「按名字找进程」都会静默失效 —— 看门狗永远「找不到 watcher」，
    于是每轮再起一个，最后几十份并存。
    只匹配 `watcher` 这一个词更糟：看门狗自己的命令行是 `host.watcher.watchdog`，
    也含这个词，**它会把自己杀掉**。所以匹配的是「watcher 后面紧跟 service」，
    斜杠点反斜杠三种写法都认（`-m host.watcher.service` 与直接跑 .py 的路径都要能匹配）。
    """
    try:
        txt = _sp.powershell(
            "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
            "Where-Object {$_.CommandLine -match " + WATCHER_PAT + "} | "
            "Select-Object -ExpandProperty ProcessId", timeout=25)
        return [t.strip() for t in txt.splitlines() if t.strip().isdigit()]
    except Exception:
        return []


def restart_watcher():
    for pid in find_watcher_pids():
        _sp.run(['taskkill', '/F', '/PID', pid], timeout=20)
        log(f'杀掉卡死 watcher PID={pid}')
    # 注意：**不要在这里手动删锁文件**。
    # proc_lock 已能识别「持有者已死」的僵尸锁并自动接管；
    # 而如果 taskkill 失败（旧进程其实还活着），删锁会让新实例照样起来 →
    # 又回到两份并存的老毛病。让锁自己判断，比我们猜更可靠。
    # 重启（继承当前环境变量，含密钥）。spawn 内部已保证无窗口 + 自动换 pythonw
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    _sp.spawn([sys.executable, WATCHER], env=env)
    log('已重启 watcher（后台无窗口）')


def main():
    # 机器角色守卫：常驻服务只能在运行端（主力机）跑。
    # 两台都跑会重复精读同一篇、重复写回 Zotero、重复烧钱，标签状态机还会互相打架。
    role.require_prod('看门狗（守护 watcher）', force=flag('--force'))
    log(f'看门狗启动。报活阈值 {STALE}s，无进展阈值 {NO_PROGRESS}s，检查间隔 {CHECK}s')
    last_restart = 0
    while True:
        alive_age, progress_age = ages()
        now = time.time()
        if now - last_restart >= GRACE:      # 刚重启的宽限期内不判死
            need, why = heartbeat.verdict(alive_age, progress_age,
                                          stale=STALE, no_progress=NO_PROGRESS)
            if need:
                log(f'{why} → 重启')
                restart_watcher()
                last_restart = now
        time.sleep(CHECK)


if __name__ == '__main__':
    # 机器角色不对时给一句人话，而不是甩一坨 traceback 到日志里 ——
    # 这个失败在主力机首次部署时必然发生一次（ROLE 默认是最安全的 dev）。
    from shared.kernel import errors as _err
    try:
        main()
    except _err.WrongMachineError as _e:
        print(str(_e))
        sys.exit(2)
