# -*- coding: utf-8 -*-
"""打开控制面板：启动 → **等它真的起来** → 再开浏览器；起不来就说清原因。

**为什么需要它**（2026-08-26 主力机实测）：

原来的 `控制面板.bat` 是「启动面板 → 固定睡 2 秒 → 开浏览器」。
两个毛病：

1. **2 秒是猜的**。机器慢一点、第一次导入慢一点，浏览器就赶在服务器绑好端口
   之前打开，用户看到「127.0.0.1 拒绝了我们的连接请求」——
   而这时候面板其实马上就要起来了，刷新一下就好。**一个纯计时的等待
   永远只是在赌**。
2. **面板真的起不来时，用户什么也看不到**。`launcher.py` 会把 traceback
   写进 `host/panel/panel_launch.log`，但没人知道该去看那个文件。

所以改成「**轮询到真的能连上为止**」，并在失败时直接把日志尾巴打出来。

用法：双击「控制面板.bat」，或 `python host/panel/open_panel.py`
"""
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

# 【标准开头】强制 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# ⚠ 和 host/deploy/update.py / host/doctor/report.py 一样，这是**引导脚本**：
#   它要在面板起不来的时候帮用户定位问题，所以自己不能依赖项目包。
#   顶层只用标准库，ROOT 从 __file__ 算。
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.join(ROOT, 'host', 'panel')
LAUNCH_LOG = os.path.join(HERE, 'panel_launch.log')

PORT = int(os.environ.get('PANEL_PORT', '8777'))
URL = f'http://127.0.0.1:{PORT}/'
WAIT_SECONDS = 30          # 冷启动 + 首次导入，给足余量
POLL_EVERY = 0.5


def alive(timeout=1.5):
    """面板在不在。连得上就算在（返回什么内容都无所谓）。"""
    try:
        urllib.request.urlopen(URL, timeout=timeout).read(1)
        return True
    except urllib.error.HTTPError:
        return True            # 有响应就说明服务器在，状态码无所谓
    except Exception:
        return False


def start_panel():
    """后台起一份面板。用 pythonw 避免弹黑窗。"""
    pyw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    exe = pyw if os.path.exists(pyw) else sys.executable
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
    subprocess.Popen([exe, os.path.join(HERE, 'launcher.py')],
                     cwd=ROOT, creationflags=flags,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def log_tail(n=25):
    if not os.path.exists(LAUNCH_LOG):
        return '（没有 panel_launch.log —— 面板可能连启动都没启动起来）'
    try:
        import io
        lines = io.open(LAUNCH_LOG, encoding='utf-8', errors='replace').read().splitlines()
        return '\n'.join(lines[-n:]) or '（日志是空的）'
    except Exception as e:
        return f'（读不了日志：{e}）'


def main():
    if alive():
        print('面板已经在跑，直接打开。')
        print('⚠ 如果你刚更新过代码，它跑的还是旧代码 —— 请先双击「更新平台.bat」，')
        print('  那里第 3 步会把旧面板停掉（见踩坑 #50）。')
        webbrowser.open(URL)
        return 0

    print('正在启动控制面板…')
    start_panel()

    deadline = time.time() + WAIT_SECONDS
    while time.time() < deadline:
        if alive():
            waited = WAIT_SECONDS - (deadline - time.time())
            print(f'启动完成（等了 {waited:.1f} 秒），正在打开浏览器：{URL}')
            webbrowser.open(URL)
            return 0
        time.sleep(POLL_EVERY)

    # ── 起不来：把该看的直接摆出来，别让用户去猜 ──
    print()
    print(f'** 面板在 {WAIT_SECONDS} 秒内没有起来 **')
    print()
    print('启动日志的最后几行（host/panel/panel_launch.log）：')
    print('─' * 60)
    print(log_tail())
    print('─' * 60)
    print()
    print('常见原因：')
    print(f'  · {PORT} 端口被别的程序占用了')
    print('  · 项目包没装好 —— 在项目文件夹里跑一次：')
    print('        python -m pip install -e . --no-deps')
    print('  · 代码有错 —— 上面日志里会有 traceback')
    print()
    print('把上面这一整段发给 Claude 即可。')
    return 1


if __name__ == '__main__':
    sys.exit(main())
