# -*- coding: utf-8 -*-
"""watcher 看门狗：监控 zotero_watcher 的心跳文件，超时无更新则判定卡死，杀掉并重启。
（工单·watcher 加心跳+看门狗，防静默卡死）

心跳：zotero_watcher 每轮写 workflow_data/logs/watcher_heartbeat.txt（unix 时间戳）。
看门狗每 CHECK 秒查一次；若心跳超过 STALE 秒没更新，重启 watcher。

用法: python watchdog.py    # 前台常驻；建议放任务计划或开机自启
"""
import os, sys, time, subprocess, io

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
HEARTBEAT = os.path.join(ROOT, 'workflow_data', 'logs', 'watcher_heartbeat.txt')
WATCHER = os.path.join(SCRIPT_DIR, 'zotero_watcher.py')
WD_LOG = os.path.join(ROOT, 'workflow_data', 'logs', 'watchdog.log')

CHECK = 60      # 每 60 秒查一次
STALE = 300     # 心跳超 300 秒（5分钟）没更新 = 卡死。watcher 轮询间隔60s，5分钟足够宽容
GRACE = 180     # 重启后给 watcher 的启动宽限期，期间不判死

def log(msg):
    line = f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}'
    print(line)
    try:
        with io.open(WD_LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass

def heartbeat_age():
    try:
        return time.time() - int(open(HEARTBEAT, encoding='utf-8').read().strip())
    except Exception:
        return None   # 心跳文件不存在/读不了

def find_watcher_pids():
    """找正在跑的 zotero_watcher 进程（Windows）。"""
    try:
        out = subprocess.run(
            ['wmic', 'process', 'where', "name='python.exe'", 'get', 'ProcessId,CommandLine'],
            capture_output=True, text=True, encoding='utf-8', errors='replace').stdout
        pids = []
        for ln in out.splitlines():
            if 'zotero_watcher' in ln:
                for tok in ln.split():
                    if tok.isdigit():
                        pids.append(tok)
        return pids
    except Exception:
        return []

def restart_watcher():
    for pid in find_watcher_pids():
        subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True)
        log(f'杀掉卡死 watcher PID={pid}')
    # 重启（继承当前环境变量，含 DEEPSEEK_KEY 等）
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    subprocess.Popen([sys.executable, WATCHER], env=env,
                     creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
    log('已重启 watcher')

def main():
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
    main()
