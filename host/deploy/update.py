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

用法：双击「更新平台.bat」，或 `python host/deploy/update.py`
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
#   而本脚本顶上 `from shared.kernel import paths, role` 直接 ModuleNotFoundError，
#   于是「用来修好环境的工具」自己先被环境卡死了）。
#
#   所以第 2 步装包之前，这里**只用标准库**，ROOT 自己算。
#   这是全项目唯一允许自己算 ROOT 的地方 —— 别处一律用 shared.kernel.paths.ROOT。
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0

# ⚠ 中文 Windows 上 PowerShell 写给管道的默认编码是 gb2312，而我们按 UTF-8 解码，
#   中文会变成乱码（实测：'停掉旧面板' → 'ͣ�������'）。
#   在脚本最前面把 PowerShell 的输出编码切成 UTF-8 就对上了。
#   本脚本是引导脚本，不能依赖 shared.kernel.subproc，所以这里内联一份。
_PS_UTF8 = '[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; '


def ps(script):
    """组一条编码正确的 PowerShell 命令行。"""
    return ['powershell', '-NoProfile', '-NonInteractive', '-Command', _PS_UTF8 + script]
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


def refresh_imports():
    """让**本进程**立刻能 import 刚装好的包。

    `pip install -e .` 是往 site-packages 写一个 .pth 文件，
    而 .pth 只在解释器**启动时**读一次 —— 所以装完包之后，
    当前这个已经跑起来的 Python 仍然 import 不到（2026-08-26 实测：
    第 2 步刚装完，第 4 步问「本机角色」还是读不到，于是跳过了重启服务）。
    """
    import importlib
    import site
    importlib.invalidate_caches()
    try:
        site.main()          # 重新处理 site-packages 里的 .pth
    except Exception:
        pass
    try:
        import shared.kernel          # noqa: F401 —— 只是试探能不能 import
        return True
    except Exception:
        pass
    if ROOT not in sys.path:
        # 引导脚本专用：装包后让本进程立刻可用，效果等同于 .pth 干的事。
        # 别处一律靠 pip install -e .，不许抄这一行（守卫会拦）。
        sys.path.insert(0, ROOT)   # paths-exempt: 引导脚本装包后自救，见上方说明
    try:
        import shared.kernel          # noqa: F401
        return True
    except Exception:
        return False


def _role():
    """装完包之后才能问「本机是什么角色」。装之前一律按最安全的 dev 处理。"""
    try:
        from shared.kernel import role
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

    只杀真正在跑面板的 python，不碰别的 python 进程。

    ⚠ 匹配必须够窄：第一版写的是 `-like '*panel*'`，结果**把自己也杀了** ——
    任何命令行里出现 "panel" 字样的 python 进程都会中招
    （实测：一条包含 `stop_panel` 字样的测试命令把自身干掉，退出码 255）。
    现在只认 `host/panel/app.py` / `launcher`，并且显式排除本进程。
    """
    if os.name != 'nt':
        return '（非 Windows，跳过）'
    me = os.getpid()
    script = (
        "$hit = Get-CimInstance Win32_Process -Filter "
        "\"Name='python.exe' or Name='pythonw.exe'\" | "
        "Where-Object { ($_.CommandLine -like '*panel*launcher*' -or "
        "$_.CommandLine -like '*panel.py*') -and "
        f"$_.ProcessId -ne {me} }}; "
        "if ($hit) { $hit | ForEach-Object { "
        "  Write-Output ('停掉旧面板 PID=' + $_.ProcessId); "
        "  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } } "
        "else { Write-Output '没有面板在跑，无需停止' }"
    )
    ok, out = run(ps(script), timeout=120, quiet=True)
    return out.strip() or '（无输出）'


def stop_watcher():
    """停掉旧 watcher，并清掉它的信号文件，好让看门狗**立刻**用新代码把它拉起来。

    **为什么光重启计划任务不够**（2026-08-27 实测）：计划任务拉起的是看门狗，
    watcher 是看门狗**另外 spawn 的独立进程**。停任务只换掉看门狗，
    老 watcher 照常活着 —— 对比两次诊断报告：看门狗 PID 变了，
    watcher PID 一模一样，新代码根本没生效。

    清信号文件是关键一步：只杀不清的话，刚被杀的 watcher 留下的是**新鲜**心跳，
    新看门狗会认为「它还活着」，要等满 300 秒才发现没人干活。
    清掉之后看门狗一上来就判「信号缺失」，当场拉起。
    """
    if os.name != 'nt':
        return '（非 Windows，跳过）'
    me = os.getpid()
    script = (
        "$hit = Get-CimInstance Win32_Process -Filter "
        "\"Name='python.exe' or Name='pythonw.exe'\" | "
        "Where-Object { $_.CommandLine -like '*deepread*watcher*' -and "
        f"$_.ProcessId -ne {me} }}; "
        "if ($hit) { $hit | ForEach-Object { "
        "  Write-Output ('停掉旧 watcher PID=' + $_.ProcessId); "
        "  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } } "
        "else { Write-Output '没有 watcher 在跑' }"
    )
    _ok, out = run(ps(script), timeout=120, quiet=True)
    msgs = [out.strip() or '（无输出）']
    try:
        from shared.kernel import heartbeat
        for kind in (heartbeat.ALIVE, heartbeat.PROGRESS):
            f = heartbeat.path('watcher', kind)
            if os.path.exists(f):
                os.remove(f)
        msgs.append('已清掉心跳/进度信号，看门狗会立刻用新代码把 watcher 拉起来')
    except Exception as e:
        msgs.append(f'（信号文件没清掉：{e} —— 看门狗最多 5 分钟后也会发现）')
    return chr(10).join(msgs)


def restart_tasks():
    """重启计划任务，让 watcher 加载新代码。只在运行端做。"""
    msgs = []
    for task in RESTART_TASKS:
        script = (f"try {{ Stop-ScheduledTask -TaskName '{task}' -ErrorAction SilentlyContinue; "
              f"Start-Sleep -Seconds 1; Start-ScheduledTask -TaskName '{task}' "
              f"-ErrorAction Stop; Write-Output '{task} 已重启' }} "
              f"catch {{ Write-Output '{task} 重启失败：' + $_.Exception.Message }}")
        _ok, out = run(ps(script), timeout=180, quiet=True)
        msgs.append(out.strip())
    return msgs


def check_unpushed():
    """本机有没有「已提交但没推送」的东西 —— 那是记事本反复弹出的根因。

    分支一旦和远程分叉，**每次 `git pull` 都会产生一个新的合并提交**，
    而 git 每次都要人给合并写说明，于是每次都弹编辑器（主力机上是记事本）。
    推上去之后两边合流，往后的拉取都是快进，就不会再弹了。
    """
    _ok, out = run(['git', 'log', '--oneline', '@{u}..HEAD'], timeout=120, quiet=True)
    ahead = [l for l in (out or '').splitlines() if l.strip()]
    _ok2, out2 = run(['git', 'status', '--short'], timeout=120, quiet=True)
    dirty = [l for l in (out2 or '').splitlines() if l.strip() and not l.startswith('??')]
    if not ahead and not dirty:
        return
    print('')
    print('-' * 60)
    if ahead:
        print(f'⚠ 本机有 {len(ahead)} 个提交还没推送到 GitHub：')
        for l in ahead[:5]:
            print('    ' + l)
        print('  只要没推上去，分支就和远程分叉，**每次 git pull 都会产生新的合并**，')
        print('  git 每次都要你给合并写说明 —— 那就是记事本反复弹出的原因。')
    if dirty:
        print('⚠ 还有改动没提交：')
        for l in dirty[:5]:
            print('    ' + l)
    # 建议要贴着实际情况给 —— 写死一条命令，遇到别的文件就会把人带沟里
    data_only = all('evalset.json' in l for l in dirty) if dirty else True
    print('  处理办法（在项目文件夹里依次跑）：')
    if dirty and not data_only:
        print('    ⚠ 本机改到了数据以外的文件。按分工，运行端只读代码、不改代码',
              '（见 docs/两台机器的分工.md）。')
        print('    先把上面这几行发给 Claude，别急着提交。')
    else:
        if dirty:
            print('      git add workflow_data/evalset.json')
            print('      git commit -m "主力机：精读评价更新"')
        print('      git push')
        print('  推完这一次，两边就合流了，以后不会再弹记事本。')
    print('-' * 60)



def main():
    total = 6
    print('\n============ 更新平台 ============')
    print('本机角色：' + _role_line())

    # ── 1. 拉代码 ──
    step(1, total, '拉取最新代码')
    # --no-edit：合并时不弹编辑器。本机分支和远程分叉过的话，`git pull` 会产生
    # 一个合并提交，git 默认要为它开编辑器让人写说明（主力机上就弹出了记事本，
    # 不关掉脚本就一直卡着）。这里是自动流程，不该等人。
    ok, out = run(['git', 'pull', '--no-edit'], timeout=600)
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
    # 离线体检要跑 pytest，那是第 5 步的上线闸门 —— 闸门跑不了等于没有闸门
    try:
        import pytest        # noqa: F401
        has_pytest = True
    except Exception:
        has_pytest = False
    if not has_pytest:
        print('顺带装上 pytest（第 5 步的离线体检要用它）…')
        run([sys.executable, '-m', 'pip', 'install', 'pytest>=8.0', '-q'], timeout=900)
    if refresh_imports():
        print('完成。本进程已能 import 项目包。')
    else:
        print('完成，但本进程仍 import 不到项目包 —— 后面几步会降级处理。')

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
        # 先停 watcher（它是看门狗 spawn 出来的独立进程，重启任务换不掉它），
        # 再重启任务，让看门狗自己也换成新代码。
        print(stop_watcher())
        for m in restart_tasks():
            print(m)
    else:
        print('本机是编程端，不注册也不重启常驻服务（跳过）')

    # ── 5. 离线体检：这一档必须全绿 ──
    step(5, total, '离线体检（不依赖 Zotero/Ollama，必须全绿）')
    ok, _ = run([sys.executable, os.path.join('host', 'doctor', 'health_check.py'), '--offline'],
                timeout=1200)
    if not ok:
        print('\n** 离线体检有失败项 —— 不要继续使用，把上面的输出发给 Claude **')
        return 1

    # ── 6. 完整体检 ──
    step(6, total, '完整体检（检查 Zotero / Ollama / 自启任务）')
    run([sys.executable, os.path.join('host', 'doctor', 'health_check.py')], timeout=1800)

    check_unpushed()

    print('\n============ 更新完成 ============')
    if no_change:
        print('（代码本来就是最新的，但服务已按新代码重启过一遍）')
    r = _role()
    if r is not None and not r.is_prod() and not r.is_test():
        print('')
        print('⚠ 本机角色是 ' + r.current() + '。如果这台是主力机，现在去改：')
        print('   双击「控制面板.bat」→ 本机设置 → 机器角色 → 填 prod → 保存')
        print('   不改的话，精读监听会拒绝启动（这是保护，不是故障）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
