# -*- coding: utf-8 -*-
"""subproc · 子进程调用基础件（公理：跑一条外部命令，安静、带超时、编码正确）

解决的真实问题（踩坑 #31）：
Windows 上用 subprocess 调 powershell/wmic/python，**默认会弹出一个控制台窗口**。
面板每 15 秒查一次进程、看门狗每 60 秒查一次，于是用户桌面不停闪蓝色窗口。
散落在 6 个文件、17 处的调用各写各的，修一处漏一处，新写的代码还会再犯。

**为什么做成积木而不是逐处修**：
逐处修只解决今天这 17 处；做成积木后，「调子进程」这件事只有一个正确入口，
以后任何新代码复用它就自动不弹窗。从源头杜绝优于事后补救。
（体检里另有一项会揪出绕过本模块的裸调用，防止规范腐坏。）

公理特征：只做「执行一条命令并拿回结果」这一件不可再分的事。

用法：
    from core.subproc import run, spawn
    r = run(['powershell', '-NoProfile', '-Command', 'Get-Date'])   # 前台，等结果
    spawn([sys.executable, 'watcher.py'])                            # 后台，不等
"""
import os, sys, subprocess

# Windows 上「不要给我弹窗」的标志；其他系统没有这个概念
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0

DEFAULT_TIMEOUT = 120


def _flags(extra=0):
    return _NO_WINDOW | extra


def _env(env=None):
    """给子进程强制 UTF-8 输出。

    **踩坑 #32**：Windows 上子进程默认按系统区域编码（中文系统是 GBK）写 stdout，
    而我们按 UTF-8 解码 → 中文全变乱码。项目里的日志、体检报告、精读进度全是中文，
    一直看到的乱码就是这么来的（长期被误当成「PowerShell 显示问题」而没深究）。
    在这里统一注入 PYTHONIOENCODING，所有调用点自动受益。
    """
    e = dict(env if env is not None else os.environ)
    e.setdefault('PYTHONIOENCODING', 'utf-8')
    e.setdefault('PYTHONUTF8', '1')      # Python 3.7+ 的 UTF-8 模式，双保险
    return e


def run(cmd, timeout=DEFAULT_TIMEOUT, cwd=None, env=None, check=False, text=True):
    """跑一条命令并等它结束，返回 CompletedProcess。

    默认行为（正是散装调用最容易漏掉的三件事）：
      - 不弹控制台窗口
      - 有超时（默认 120 秒），不会永远挂住
      - UTF-8 解码且容错，中文输出不会炸

    check=True 时命令失败会抛 CalledProcessError。
    """
    return subprocess.run(
        cmd, capture_output=True, text=text,
        encoding='utf-8' if text else None,
        errors='replace' if text else None,
        timeout=timeout, cwd=cwd, env=_env(env), check=check,
        creationflags=_flags())


def out(cmd, timeout=DEFAULT_TIMEOUT, cwd=None, env=None, default=''):
    """只要标准输出的便捷版。命令失败或超时返回 default，不抛异常。

    适合「查点信息，查不到就算了」的场景（面板刷新、状态探测），
    这类地方不该因为一次抖动就报错打断。
    """
    try:
        return run(cmd, timeout=timeout, cwd=cwd, env=env).stdout or default
    except Exception:
        return default


def spawn(cmd, cwd=None, env=None, use_pythonw=True):
    """后台启动一个长期运行的进程，不等待、不弹窗、不占用父进程的输入输出。

    use_pythonw=True 时，若命令是 python.exe 会自动换成 pythonw.exe ——
    双保险：即使调用方自己是带控制台的 python 起的，被启动的服务也不会带窗口。
    """
    cmd = list(cmd)
    if use_pythonw and os.name == 'nt' and cmd and cmd[0].endswith('python.exe'):
        pyw = cmd[0].replace('python.exe', 'pythonw.exe')
        if os.path.exists(pyw):
            cmd[0] = pyw
    return subprocess.Popen(
        cmd, cwd=cwd, env=_env(env), creationflags=_flags(),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL)


def powershell(script, timeout=DEFAULT_TIMEOUT, default=''):
    """跑一段 PowerShell 并返回输出。-NoProfile 避免加载用户配置（快且可预期）。"""
    return out(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
               timeout=timeout, default=default)
