# -*- coding: utf-8 -*-
"""proc_lock · 单实例锁基础件（公理：保证同一个程序同时只跑一份）

解决的真实问题（踩坑 #30）：
zotero_watcher 反复出现 2 个实例并存 —— 任务计划自启一份、看门狗又启一份，
两份同时轮询同一个 Zotero 库，会抢同一篇文献的处理权，导致重复精读、重复上传。

**为什么用锁而不是靠看门狗去杀**：
杀是事后补救，永远有时间窗（旧的还没死、新的已经在跑）；
锁是事前阻断，第二份根本起不来。从源头杜绝优于事后清理。

公理特征：只做「抢占一个具名的独占权」这一件不可再分的事。

用法：
    from modules.proc_lock import single_instance
    if not single_instance('zotero_watcher'):
        sys.exit('已有一份在跑，本次退出')
    # 往下就是唯一实例

锁会在进程退出时自动释放（含被强杀的情况：靠 PID 存活检测识别僵尸锁）。
"""
import os, sys, atexit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCK_DIR = os.path.join(ROOT, 'workflow_data', 'logs')

_held = []          # 本进程持有的锁文件路径，退出时清理


def _lock_path(name):
    return os.path.join(LOCK_DIR, f'{name}.lock')


def _pid_alive(pid):
    """该 PID 是否还活着。判断不了时保守返回 True（宁可拦住，不可放两份进来）。"""
    if pid <= 0:
        return False
    if os.name == 'nt':
        import subprocess
        try:
            out = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'],
                                 capture_output=True, text=True, timeout=10).stdout
            return str(pid) in out
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True


def holder(name):
    """当前谁持有这把锁。返回 PID；没人持有或锁已失效返回 None。"""
    p = _lock_path(name)
    if not os.path.exists(p):
        return None
    try:
        pid = int(open(p, encoding='utf-8').read().strip() or 0)
    except Exception:
        return None
    return pid if _pid_alive(pid) else None


def single_instance(name):
    """抢锁。抢到返回 True（本进程是唯一实例），已有活着的实例返回 False。

    僵尸锁（持有者已死）会被自动接管，不需要人工删文件 ——
    否则一次崩溃就会让服务再也起不来，比重复实例更糟。
    """
    os.makedirs(LOCK_DIR, exist_ok=True)
    p = _lock_path(name)
    alive = holder(name)
    if alive and alive != os.getpid():
        return False
    if alive == os.getpid():
        return True
    try:
        # O_EXCL 保证并发下只有一个进程能创建成功；僵尸锁先删再抢
        if os.path.exists(p):
            os.remove(p)
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        return False    # 极小概率的并发竞争，对方赢了
    except Exception:
        return True     # 锁机制本身故障时不阻断主功能（可用性优先于洁癖）
    _held.append(p)
    return True


def release(name=None):
    """主动释放锁。一般不用调，进程退出时会自动清理。"""
    targets = [_lock_path(name)] if name else list(_held)
    for p in targets:
        try:
            if os.path.exists(p) and open(p, encoding='utf-8').read().strip() == str(os.getpid()):
                os.remove(p)
        except Exception:
            pass
        if p in _held:
            _held.remove(p)


atexit.register(release)
