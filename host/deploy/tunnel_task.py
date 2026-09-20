# -*- coding: utf-8 -*-
"""tunnel_task · 编程机上注册 / 注销「文献平台隧道」自启任务（给 Antigravity 用）。

主力机的 MCP HTTP 服务只绑它自己的 127.0.0.1:8778，编程机上的 Antigravity 要用，
得先有一条 SSH 隧道把它接到本机 8778。原来靠用户双击一个窗口并一直开着；
窗口一关、电脑一重启就断，Antigravity 报「connectex: 目标计算机积极拒绝」，
用户看不出是隧道没开（2026-09-19）。

这份把隧道注册成**登录即启、无窗口、断了自己重连**的计划任务，跑的是
`launch/不常用/文献平台隧道（后台自启）.ps1`（重连逻辑在那份脚本里）。

⚠ 这是「A 机不注册自启任务」约定的**唯一例外**：它只往外连、不花钱、不写库、
不碰数据，坏了的后果只是 Antigravity 连不上。主力机上不许装（它不需要连自己）。

用法：
    python host/deploy/tunnel_task.py --install    # 注册并立刻启动
    python host/deploy/tunnel_task.py --remove     # 注销并停掉
    python host/deploy/tunnel_task.py              # 看状态
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.kernel import role, subproc
from shared.kernel.cli import flag, wants_help

TASK = 'LiteraturePlatformTunnel'
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, 'launch', '不常用', '文献平台隧道（后台自启）.ps1')
PORT = 8778


def _ps(script, timeout=60):
    out = subproc.powershell(script, timeout=timeout, default=None)
    return out is not None, (out or '').strip()


def status():
    ok, out = _ps(f"$t = Get-ScheduledTask -TaskName '{TASK}' -ErrorAction SilentlyContinue; "
                  f"if ($t) {{ $t.State }} else {{ '未注册' }}")
    listening = bool(_ps(f"if (Get-NetTCPConnection -LocalPort {PORT} -State Listen -ErrorAction SilentlyContinue) {{ 'y' }}")[1])
    return out if ok else '（查询失败）' + out, listening


def install():
    if role.is_prod():
        print('这是主力机，不需要连自己 —— 隧道只在编程机上装。')
        return 1
    if not os.path.exists(SCRIPT):
        print(f'找不到隧道脚本：{SCRIPT}')
        return 1
    script = (
        f"$a = New-ScheduledTaskAction -Execute 'powershell.exe' "
        f"-Argument '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"{SCRIPT}\"'; "
        f"$tr = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; "
        f"$st = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) "
        f"-RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable "
        f"-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; "
        f"Register-ScheduledTask -TaskName '{TASK}' -Action $a -Trigger $tr -Settings $st "
        f"-Description '把主力机的文献平台 MCP 服务接到本机 {PORT}，给 Antigravity 用（断了自动重连）' "
        f"-Force | Out-Null; Start-ScheduledTask -TaskName '{TASK}'; '已注册并启动'"
    )
    ok, out = _ps(script, timeout=120)
    print(out)
    return 0 if ok else 1


def remove():
    ok, out = _ps(f"Stop-ScheduledTask -TaskName '{TASK}' -ErrorAction SilentlyContinue; "
                  f"Unregister-ScheduledTask -TaskName '{TASK}' -Confirm:$false -ErrorAction SilentlyContinue; "
                  f"Get-CimInstance Win32_Process -Filter \"Name='ssh.exe'\" | "
                  f"Where-Object {{ $_.CommandLine -like '*{PORT}:127.0.0.1:{PORT}*' }} | "
                  f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}; '已注销并停掉'")
    print(out)
    return 0 if ok else 1


def main():
    if wants_help():
        print(__doc__)
        return 0
    if flag('--install'):
        return install()
    if flag('--remove'):
        return remove()
    state, listening = status()
    print(f'任务 {TASK}：{state}；本机 {PORT} 端口：{"在听（隧道通）" if listening else "没人在听（隧道没起来）"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
