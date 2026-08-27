# -*- coding: utf-8 -*-
"""watcher 看门狗：监控 zotero_watcher 的心跳文件，超时无更新则判定卡死，杀掉并重启。
（工单·watcher 加心跳+看门狗，防静默卡死）

心跳：zotero_watcher 每轮写 workflow_data/logs/watcher_heartbeat.txt（unix 时间戳）。
看门狗每 CHECK 秒查一次；若心跳超过 STALE 秒没更新，重启 watcher。

用法: python watchdog.py    # 前台常驻；建议放任务计划或开机自启
"""
import os, sys, time, subprocess

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from core import paths, role
from core.cli import flag
from core.paths import ROOT as _ROOT

from core import subproc as _sp   # 统一走静默子进程调用，避免弹窗

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = _ROOT
HEARTBEAT = paths.runtime('watcher_heartbeat.txt')
WATCHER = os.path.join(SCRIPT_DIR, 'zotero_watcher.py')

CHECK = 60      # 每 60 秒查一次
STALE = 300     # 心跳超 300 秒（5分钟）没更新 = 卡死。watcher 轮询间隔60s，5分钟足够宽容
GRACE = 180     # 重启后给 watcher 的启动宽限期，期间不判死


from core.log import get_logger
log = get_logger('watchdog')   # 统一日志：时间戳 + 落盘 + 自动轮转


def heartbeat_age():
    try:
        return time.time() - int(open(HEARTBEAT, encoding='utf-8').read().strip())
    except Exception:
        return None   # 心跳文件不存在/读不了


def find_watcher_pids():
    """找正在跑的 zotero_watcher 进程（Windows）。

    走 subproc 积木：本函数每 60 秒被调一次，裸调 wmic 会不停弹控制台窗口（踩坑 #31）。
    wmic 在新版 Windows 已弃用，改用 PowerShell 的 CIM 查询，更可靠。
    """
    try:
        txt = _sp.powershell(
            "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
            "Where-Object {$_.CommandLine -match 'zotero_watcher'} | "
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
    log(f'看门狗启动。心跳阈值 {STALE}s，检查间隔 {CHECK}s')
    last_restart = 0
    while True:
        age = heartbeat_age()
        now = time.time()
        if now - last_restart < GRACE:
            pass  # 刚重启，宽限期内不判死
        elif age is None:
            log('心跳文件缺失，可能 watcher 未启动 → 重启')
            restart_watcher(); last_restart = now
        elif age > STALE:
            log(f'心跳已 {int(age)}s 未更新（>{STALE}）→ 判定卡死，重启')
            restart_watcher(); last_restart = now
        time.sleep(CHECK)


if __name__ == '__main__':
    # 机器角色不对时给一句人话，而不是甩一坨 traceback 到日志里 ——
    # 这个失败在主力机首次部署时必然发生一次（ROLE 默认是最安全的 dev）。
    from core import errors as _err
    try:
        main()
    except _err.WrongMachineError as _e:
        print(str(_e))
        sys.exit(2)
