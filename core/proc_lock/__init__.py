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
    from core.proc_lock import single_instance
    if not single_instance('zotero_watcher'):
        sys.exit('已有一份在跑，本次退出')
    # 往下就是唯一实例

锁会在进程退出时自动释放（含被强杀的情况：靠 PID 存活检测识别僵尸锁）。
"""
import os, sys, atexit
from core import paths

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCK_DIR = paths.LOGS

_held = []          # 本进程持有的锁文件路径，退出时清理


def _lock_path(name):
    return os.path.join(LOCK_DIR, f'{name}.lock')


def _pid_alive(pid):
    """该 PID 是否还活着。判断不了时保守返回 True（宁可拦住，不可放两份进来）。"""
    if pid <= 0:
        return False
    if os.name == 'nt':
        try:
            # 走 subproc 积木：裸调 tasklist 会弹控制台窗口（踩坑 #31）
            from core.subproc import out as _out
            # ⚠ 默认值必须是 None 而不是 ''（踩坑 #44）：
            # tasklist 超时/失败时 out() 返回默认值，若默认值是 '' 则 `pid in ''` == False，
            # 于是「查不到」被当成「进程已死」→ 抢走锁 → 第二个 watcher 起来 → 回归踩坑 #30。
            # 本函数的契约是「判断不了时保守返回 True」，默认值就得让这条路走到 True。
            txt = _out(['tasklist', '/FI', f'PID eq {pid}', '/NH', '/FO', 'CSV'],
                       timeout=10, default=None)
            if txt is None:
                return True                     # 查不到 ≠ 死了
            # CSV 格式下 PID 是独立带引号的字段，如 "python.exe","12345","Console",...
            # 不能用裸子串匹配：内存列形如 "45,678 K"，pid=678 会假匹配成「活着」。
            return f'"{pid}"' in txt
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
    # ⚠ 不能「先无条件删掉旧锁再 O_EXCL 创建」（踩坑 #44）：
    # 那个 remove 到 create 之间的窗口里，另一个进程可能刚建好自己的锁而被我们删掉，
    # 结果两份都以为自己是唯一实例 —— 计划任务与看门狗同时开机启动时正好撞上这个窗口。
    # 改成：先抢建；撞到已存在的锁，确认是僵尸后用「原子改名」争夺接管权
    # （os.rename 对同一个源文件只可能成功一次，输的那个拿到 FileNotFoundError）。
    for _ in range(2):
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
        except FileExistsError:
            if holder(name) is not None:
                return False            # 锁的主人还活着，本次老实退出
            try:
                stale = f'{p}.stale{os.getpid()}'
                os.rename(p, stale)     # 只有一个进程能改名成功 = 只有一个能接管
                os.remove(stale)
            except OSError:
                pass                    # 接管权被别人抢走了，下一轮会看到它建的新锁
            continue
        except Exception:
            return True     # 锁机制本身故障时不阻断主功能（可用性优先于洁癖）
        _held.append(p)
        return True
    return False


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
