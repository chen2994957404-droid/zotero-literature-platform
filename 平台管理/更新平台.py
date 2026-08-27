# -*- coding: utf-8 -*-
"""上线：把编程端改好的代码拉到本机，并**重启跑着旧代码的服务**。

**为什么不是一个纯 .bat**（2026-08-26 踩坑）：

第一版 `更新平台.bat` 只做了 `git pull` + 重装 + 体检，**没有重启服务**。
结果主力机更新后打开控制面板，新加的「机器角色」设置项**根本不显示** ——
因为面板是常驻进程，占着 8777 端口跑着旧代码；
`控制面板.bat` 新起的进程绑不上端口直接死了，浏览器连的还是那个老进程。

同样的问题也会发生在 watcher 上：计划任务里跑的是更新前加载的代码，
不重启就一直是旧的，而且**没有任何迹象表明它是旧的**。

> 教训：**部署不等于把文件换掉。** 只要有常驻进程，
> 「更新代码」和「让新代码生效」就是两件事，后者必须显式做。

## 顺序为什么是这样

`git pull` 放在 Python 里而不是 .bat 里，是因为 Python 启动时就把整个文件
读进内存了，所以这个脚本**可以安全地更新自己** —— 本次运行仍用旧逻辑跑完，
下次运行才用新逻辑。放在 .bat 里则可能读到改到一半的文件。

用法：双击「更新平台.bat」，或 `python 平台管理/更新平台.py`
"""
import os
import subprocess
import sys
import time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# ⚠ 这是**引导脚本**：它必须能在「包还没装好」的机器上跑起来，
#   因为「装包」正是它要做的事之一（2026-08-26 踩坑：主力机从没装过包，
#   而本脚本顶上 `from core import paths, role` 直接 ModuleNotFoundError，
#   于是「用来修好环境的工具」自己先被环境卡死了）。
#
#   所以第 2 步装包之前，这里**只用标准库**，ROOT 自己算。
#   这是全项目唯一允许自己算 ROOT 的地方 —— 别处一律用 core.paths.ROOT。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
PANEL_PORT = int(os.environ.get('PANEL_PORT', '8777'))

# 更新后需要重启才能生效的计划任务（只在运行端有）
RESTART_TASKS = ['ZoteroLiteratureWatcher']


def run(cmd, timeout=900, quiet=False):
    """跑一条命令并把输出直接打给用户看。返回 (成功?, 输出)。"""
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=timeout,
                           creationflags=_NOWIN)
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'
    out = (r.stdout or '') + (r.stderr or '')
    if not quiet:
        print(out.rstrip())
    return r.returncode == 0, out


def _role():
    """装完包之后才能问「本机是什么角色」。装之前一律按最安全的 dev 处理。"""
    try:
        from core import role
        return role
    except Exception:
        return None


def _role_line():
    r = _role()
    if r is None:
        return '（包还没装好，暂时读不到角色 —— 第 2 步装完就有了）'
    return (f'{r.current()}（{r.label()}）'
            + ('' if r.is_configured() else '   ⚠ 未显式设置'))


def step(n, total, title):
    print(f'\n[{n}/{total}] {title}')
    print('─' * 60)


def stop_panel():
    """停掉正在跑的控制面板进程（它占着端口、跑着旧代码）。

    只杀跑 panel 的 python，不碰别的 python 进程 —— 用命令行特征匹配。
    """
    if os.name != 'nt':
        return '（非 Windows，跳过）'
    ps = (
        "$hit = Get-CimInstance Win32_Process -Filter "
        "\"Name='python.exe' or Name='pythonw.exe'\" | "
        "Where-Object { $_.CommandLine -like '*panel*' }; "
        "if ($hit) { $hit | ForEach-Object { "
        "  Write-Output ('停掉旧面板 PID=' + $_.ProcessId); "
        "  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } } "
        "else { Write-Output '没有面板在跑，无需停止' }"
    )
    ok, out = run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
                  timeout=120, quiet=True)
    return out.strip() or '（无输出）'


def restart_tasks():
    """重启计划任务，让 watcher 加载新代码。只在运行端做。"""
    msgs = []
    for task in RESTART_TASKS:
        ps = (f"try {{ Stop-ScheduledTask -TaskName '{task}' -ErrorAction SilentlyContinue; "
              f"Start-Sleep -Seconds 1; Start-ScheduledTask -TaskName '{task}' "
              f"-ErrorAction Stop; Write-Output '{task} 已重启' }} "
              f"catch {{ Write-Output '{task} 重启失败：' + $_.Exception.Message }}")
        _ok, out = run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
                       timeout=180, quiet=True)
        msgs.append(out.strip())
    return msgs


def main():
    total = 6
    print('\n============ 更新平台 ============')
    print('本机角色：' + _role_line())

    # ── 1. 拉代码 ──
    step(1, total, '拉取最新代码')
    ok, out = run(['git', 'pull'], timeout=600)
    if not ok:
        print('\n** 拉取失败 **')
        print('最常见的原因：这台机器上改过代码。本机不该改代码，改动请在编程端做。')
        print('把上面的报错发给 Claude。')
        return 1
    no_change = 'Already up to date' in out or '已经是最新' in out

    # ── 2. 重装包 ──
    step(2, total, '更新包登记（pip install -e .）')
    ok, _ = run([sys.executable, '-m', 'pip', 'install', '-e', '.', '--no-deps', '-q'],
                timeout=900)
    if not ok:
        print('\n** 安装失败，把上面的报错发给 Claude **')
        return 1
    print('完成。')

    # ── 3. 停旧面板 ──
    step(3, total, '停掉跑着旧代码的控制面板')
    print(stop_panel())
    print('（下次双击「控制面板.bat」会用新代码启动）')

    # ── 4. 重启常驻服务 ──
    step(4, total, '重启常驻服务，让新代码生效')
    r = _role()
    if r is None:
        print('读不到本机角色（包没装好？），保守起见跳过重启')
    elif r.is_prod():
        for m in restart_tasks():
            print(m)
    else:
        print('本机是编程端，不注册也不重启常驻服务（跳过）')

    # ── 5. 离线体检：这一档必须全绿 ──
    step(5, total, '离线体检（不依赖 Zotero/Ollama，必须全绿）')
    ok, _ = run([sys.executable, os.path.join('平台管理', 'health_check.py'), '--offline'],
                timeout=1200)
    if not ok:
        print('\n** 离线体检有失败项 —— 不要继续使用，把上面的输出发给 Claude **')
        return 1

    # ── 6. 完整体检 ──
    step(6, total, '完整体检（检查 Zotero / Ollama / 自启任务）')
    run([sys.executable, os.path.join('平台管理', 'health_check.py')], timeout=1800)

    print('\n============ 更新完成 ============')
    if no_change:
        print('（代码本来就是最新的，但服务已按新代码重启过一遍）')
    r = _role()
    if r is not None and not r.is_prod():
        print('')
        print('⚠ 本机角色是 ' + r.current() + '。如果这台是主力机，现在去改：')
        print('   双击「控制面板.bat」→ 本机设置 → 机器角色 → 填 prod → 保存')
        print('   不改的话，精读监听会拒绝启动（这是保护，不是故障）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
