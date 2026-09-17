# -*- coding: utf-8 -*-
"""看门狗 = 平台常驻进程的总管：该活着的拉起来、真死了的重启 —— **但绝不打断正在干活的**。

## 管三个进程（2026-09-17 起，之前只管 watcher 一个）

| 进程 | 干什么 | 形态 |
|---|---|---|
| `host.watcher.service` | 盯 Zotero 标签 → 精读 → 回写（花钱、要人打标签） | 常驻 |
| `host.ingest --loop`   | 落地流水线：正本一到就解析 / 骨架 / 向量化（不花模型钱） | 常驻 |
| `host.daily`           | 每天一次：盯新刊 + 补摘要 + 自动升 1 级取件 | 跑完就退出，一天拉一次 |

**为什么拆开**（用户 2026-09-17 定）：这三件事原来全挤在 watcher 的一个循环里串着做 ——
每天一次的盯新刊要补几千篇摘要、借浏览器取十篇文献，一跑就是几十分钟，
这期间用户打的「待处理」标签得干等；落地流水线每轮解析几篇也一样挡精读。
本来就是不同的活，就该是不同的进程：一个慢了不拖累另一个，各自有自己的锁和心跳。
三个都是 I/O 等待型（等 MineRU、等 DeepSeek、等浏览器），同时开着不吃本机资源。

## 判「死」的两个信号（都由 `shared.kernel.heartbeat` 维护，那里有完整说明）

    <名>_heartbeat.txt   后台线程固定节奏写   → 进程还活着吗
    <名>_progress.txt    每完成一件实事时写   → 还在往前推进吗

**为什么要两个**（2026-08-27 从主力机日志查出来的真问题）：
原来只有一个心跳，写在轮询循环开头，精读期间根本不写。
而精读一篇远不止 5 分钟 —— 于是看门狗每次都把**正在干活的 watcher 杀掉**，
一个月误杀约 20 次，每次都白花一份 MineRU + DeepSeek，还在库里留下半成品。

拆开之后：精读跑一小时也不会被误杀（后台仍在报活）；
进程真死了 5 分钟内发现；活着但卡在某个不返回的调用上，由进度阈值兜底。

用法: python -m host.watcher.watchdog    # 前台常驻；日常由任务计划 ZoteroLiteratureWatcher 自启
"""
import os, sys, time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from shared.kernel import heartbeat, paths, role
from shared.kernel.cli import flag
from shared.kernel.paths import ROOT as _ROOT

from shared.kernel import subproc as _sp   # 统一走静默子进程调用，避免弹窗

ROOT = _ROOT

CHECK = 60          # 每 60 秒查一次
STALE = 300         # 超 300 秒没报活 = 进程死了/冻住了。后台线程每 30 秒写一次，很宽容
NO_PROGRESS = 2700  # 报活正常但 45 分钟毫无进展 = 卡在某个不返回的调用上。
                    # 这个阈值必须**大于最慢一篇精读的耗时**，否则又变回误杀
GRACE = 180         # 重启后给进程的启动宽限期，期间不判死

# ── 常驻进程表 ──────────────────────────────────────────────────────────────
# beacon：它用 heartbeat.start(<beacon>) 报活的名字（测试会核对 service 源码里真用的是这个名）
# pat：   在进程列表里认它的正则。**认模块路径，不认单个词**（踩坑 #81 的第三次复发预防）：
#         这里搬过两次家，每搬一次「按名字找进程」都静默失效 → 看门狗永远「找不到」→ 每轮再起一个。
#         只匹配 `watcher` 更糟：看门狗自己的命令行 `host.watcher.watchdog` 也含它，**会把自己杀掉**。
#         PowerShell 单引号串里反斜杠是字面量，所以这一串原样就是正则；点 / 斜杠 / 反斜杠三种写法都认。
SERVICES = [
    {'name': 'watcher', 'beacon': 'watcher', 'module': 'host.watcher.service', 'args': [],
     'pat': "'watcher[\\\\./]service'", 'no_progress': NO_PROGRESS},
    {'name': 'ingest',  'beacon': 'ingest',  'module': 'host.ingest', 'args': ['--loop'],
     'pat': "'host[\\\\./]ingest'",          'no_progress': NO_PROGRESS},
]
BEACON = SERVICES[0]['beacon']     # 老名字，测试与日志还在用

# 看门狗拉起的进程各自持有的单实例锁（`shared.kernel.proc_lock`）。
# **重启计划任务时要按这些锁把它们全停掉**：任务停的只是看门狗，孙子进程照跑旧代码（踩坑 #62）——
# 面板的重启按钮与 `host.deploy.update` 都从这里取，别各写一份。
CHILD_LOCKS = ('zotero_watcher', 'ingest_loop', 'daily')
# 锁名 → 它的报活名。杀完顺手把报活文件删掉，新看门狗第一轮就把它拉起来 ——
# 不删的话报活文件还新鲜（后台线程 30 秒写一次），要等 5 分钟过期才重启（2026-09-17 部署时实测）。
_LOCK_BEACON = {'zotero_watcher': 'watcher', 'ingest_loop': 'ingest'}


def kill_children(run):
    """按锁文件把三个孙子进程停掉。`run(cmd, timeout)` 由调用方给（面板与部署各有自己的静默 run）。"""
    from shared.kernel.proc_lock import holder
    killed = []
    for lock in CHILD_LOCKS:
        pid = holder(lock)
        if pid:
            run(['taskkill', '/PID', str(pid), '/F'], timeout=30)
            killed.append(f'{lock}={pid}')
            beacon = _LOCK_BEACON.get(lock)
            if beacon:
                try:
                    os.remove(heartbeat.path(beacon, heartbeat.ALIVE))
                except OSError:
                    pass
    return killed

# ── 每日一次的作业 ───────────────────────────────────────────────────────────
DAILY_MODULE = 'host.daily'
DAILY_AFTER = 2 * 3600     # 每天 02:00 之后才拉（那会儿没人在打标签，Crossref / OpenAlex 也空）
DAILY_STAMP = 'daily_last_run'   # paths.runtime 里记「上次拉起是哪天」


def ages(beacon=BEACON):
    """(距上次报活多少秒, 距上次有进展多少秒)。读不到就是 None。"""
    return (heartbeat.age(beacon, heartbeat.ALIVE),
            heartbeat.age(beacon, heartbeat.PROGRESS))


def find_pids(pat):
    """按命令行正则找进程（Windows）。

    走 subproc 模块：本函数每 60 秒被调一次，裸调 wmic 会不停弹控制台窗口（踩坑 #31）。
    wmic 在新版 Windows 已弃用，改用 PowerShell 的 CIM 查询，更可靠。
    """
    try:
        txt = _sp.powershell(
            "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
            "Where-Object {$_.CommandLine -match " + pat + "} | "
            "Select-Object -ExpandProperty ProcessId", timeout=25)
        return [t.strip() for t in txt.splitlines() if t.strip().isdigit()]
    except Exception:
        return []


def find_watcher_pids():
    return find_pids(SERVICES[0]['pat'])


def spawn_module(module, args=()):
    """后台无窗口起 `python -m <module>`，继承当前环境变量（含密钥）。spawn 内部会自动换 pythonw。"""
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    return _sp.spawn([sys.executable, '-m', module, *args], cwd=ROOT, env=env)


def restart_service(svc):
    for pid in find_pids(svc['pat']):
        _sp.run(['taskkill', '/F', '/PID', pid], timeout=20)
        log(f'杀掉卡死的 {svc["name"]} PID={pid}')
    # 注意：**不要在这里手动删锁文件**。
    # proc_lock 已能识别「持有者已死」的僵尸锁并自动接管；
    # 而如果 taskkill 失败（旧进程其实还活着），删锁会让新实例照样起来 →
    # 又回到两份并存的老毛病。让锁自己判断，比我们猜更可靠。
    spawn_module(svc['module'], svc['args'])
    log(f'已重启 {svc["name"]}（{svc["module"]}，后台无窗口）')


def restart_watcher():
    restart_service(SERVICES[0])


def _read_stamp():
    try:
        return open(paths.runtime(DAILY_STAMP + '.txt'), encoding='utf-8').read().strip()
    except Exception:
        return ''


def _write_stamp(day):
    try:
        with open(paths.runtime(DAILY_STAMP + '.txt'), 'w', encoding='utf-8') as f:
            f.write(day)
    except Exception:
        pass


def daily_due(now=None, last_day=None):
    """今天该拉每日作业了吗。**纯函数**，便于测：

    - 今天已经拉过 → 不
    - 还没到 DAILY_AFTER（凌晨两点）→ 不（刚开机是白天也一样，等到明天凌晨；
      但如果**昨天根本没跑**，比如机器昨晚关着，那今天一到点就补）
    """
    now = now or time.time()
    lt = time.localtime(now)
    today = time.strftime('%Y-%m-%d', lt)
    last_day = _read_stamp() if last_day is None else last_day
    if last_day == today:
        return False
    since_midnight = lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec
    return since_midnight >= DAILY_AFTER


def launch_daily():
    """拉一次每日作业。作业自己有单实例锁，重复拉是安全的。"""
    _write_stamp(time.strftime('%Y-%m-%d'))
    spawn_module(DAILY_MODULE)
    log(f'已拉起每日作业（{DAILY_MODULE}：盯新刊 + 补摘要 + 升 1 级取件）')


from shared.kernel.log import get_logger
log = get_logger('watchdog')   # 统一日志：时间戳 + 落盘 + 自动轮转


def main():
    # 机器角色守卫：常驻服务只能在运行端（主力机）跑。
    # 两台都跑会重复精读同一篇、重复写回 Zotero、重复烧钱，标签状态机还会互相打架。
    role.require_prod('看门狗（守护 watcher / 落地流水线 / 每日作业）', force=flag('--force'))
    log(f'看门狗启动。管 {len(SERVICES)} 个常驻进程 + 每日作业；'
        f'报活阈值 {STALE}s，无进展阈值 {NO_PROGRESS}s，检查间隔 {CHECK}s')
    last_restart = {s['name']: 0 for s in SERVICES}
    while True:
        now = time.time()
        for svc in SERVICES:
            if now - last_restart[svc['name']] < GRACE:      # 刚重启的宽限期内不判死
                continue
            alive_age, progress_age = ages(svc['beacon'])
            need, why = heartbeat.verdict(alive_age, progress_age,
                                          stale=STALE, no_progress=svc['no_progress'])
            if need:
                log(f'[{svc["name"]}] {why} → 重启')
                restart_service(svc)
                last_restart[svc['name']] = now
        try:
            if daily_due(now):
                launch_daily()
        except Exception as e:
            log(f'拉每日作业失败：{type(e).__name__}: {e}')
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
