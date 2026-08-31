# -*- coding: utf-8 -*-
"""一键诊断报告 —— 把这台机器的状态打成一个自包含的文件。

**为什么需要它**（见 docs/两台机器的分工.md 第四节）：

Claude Code 只在编程端（A 机）。主力机（B 机）出问题时，
Claude **看不见那台机器的任何东西** —— 能拿到的只有用户复制粘贴的内容。

所以这个脚本的目标是：**一次把该看的全给全，避免来回追问**。
一次往返（你双击 → 把报告丢给 Claude）就能定位问题，而不是问五轮。

用法：双击「诊断报告.bat」，或 `python host/doctor/report.py`
产物：workflow_data/logs/诊断报告.txt（同时尝试复制到剪贴板）
"""
import io
import os
import subprocess
import sys
import time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# ⚠ 诊断报告是「出问题时才用」的工具，所以它**必须在环境坏掉时也能跑**。
#   包没装好（主力机就发生过）时不能直接 ModuleNotFoundError 死掉 ——
#   那等于「体温计要求你先退烧」。读不到就降级，并把这件事本身写进报告。
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from shared.kernel import paths, role
    from shared.kernel.cli import opt
    CORE_OK, CORE_ERR = True, ''
except Exception as _e:                       # noqa: BLE001 —— 什么原因都要能出报告
    paths = role = None
    CORE_OK, CORE_ERR = False, f'{type(_e).__name__}: {_e}'

    def opt(_name, default=None):
        return default

_NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0

# ⚠ 中文 Windows 上 PowerShell 写给管道的默认编码是 gb2312，而我们按 UTF-8 解码，
#   中文会变成乱码（实测：'停掉旧面板' → 'ͣ�������'）。
#   在脚本最前面把 PowerShell 的输出编码切成 UTF-8 就对上了。
#   本脚本是引导脚本，不能依赖 shared.kernel.subproc，所以这里内联一份。
_PS_UTF8 = '[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; '


def ps(script):
    """组一条编码正确的 PowerShell 命令行。"""
    return ['powershell', '-NoProfile', '-NonInteractive', '-Command', _PS_UTF8 + script]
SEP = '=' * 72


def _run(cmd, timeout=600):
    """跑一条命令，返回输出文本。失败也返回文本而不是抛异常 ——
    诊断报告的价值就在于「哪怕系统坏了也能出报告」。"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=timeout, cwd=ROOT,
                           creationflags=_NOWIN)
        return (r.stdout or '') + (('\n[stderr]\n' + r.stderr) if r.stderr.strip() else '')
    except subprocess.TimeoutExpired:
        return f'（超时 {timeout}s，未跑完）'
    except Exception as e:
        return f'（跑不起来：{type(e).__name__}: {e}）'


def _tail(path, n=120):
    if not os.path.exists(path):
        return '（文件不存在 —— 这本身可能就是线索）'
    try:
        lines = io.open(path, encoding='utf-8', errors='replace').read().splitlines()
        head = f'（共 {len(lines)} 行，取最后 {min(n, len(lines))} 行）\n'
        return head + '\n'.join(lines[-n:])
    except Exception as e:
        return f'（读不了：{e}）'


def _section(title, body):
    return f'\n{SEP}\n== {title}\n{SEP}\n{body}\n'


def collect():
    out = []
    out.append(f'诊断报告 · 生成于 {time.strftime("%Y-%m-%d %H:%M:%S")}')
    if CORE_OK:
        out.append(f'机器角色：{role.current()}（{role.label()}）'
                   f'{"" if role.is_configured() else "  ⚠ 未显式设置，按默认 dev 处理"}')
    else:
        out.append('⚠⚠ 项目包没装好，读不到本机配置：' + CORE_ERR)
        out.append('    修法：在项目文件夹里跑一次  python -m pip install -e . --no-deps')
        out.append('    （或双击「更新平台.bat」，它的第 2 步就是装包）')
    out.append(f'项目路径：{ROOT}')
    out.append(f'Python：{sys.version.split()[0]}  {sys.executable}')

    # ── 代码版本（判断这台机器有没有拿到最新改动）──
    out.append(_section('代码版本（最近 8 次提交）', _run(
        ['git', 'log', '--oneline', '-8'], timeout=60)))
    out.append(_section('工作区是否干净（B 机应当干净：不在 B 上改代码）', _run(
        ['git', 'status', '--short', '--branch'], timeout=60)))

    # ── 体检（完整档）──
    out.append(_section('完整档体检', _run(
        [sys.executable, os.path.join('host', 'doctor', 'health_check.py')], timeout=900)))

    # ── 数据资产 ──
    try:
        if not CORE_OK:
            raise RuntimeError('包没装好，读不到数据契约')
        keys = paths.all_keys()
        import glob
        n_struct = len(glob.glob(os.path.join(paths.STRUCTURED, '*.json')))
        data = [f'library 已归档文献：{len(keys)} 篇',
                f'structured 抽取结果：{n_struct} 条',
                f'向量库目录：{"在" if os.path.isdir(paths.VECTOR_DB) else "缺失"}']
        try:
            from shared.adapters import vectordb
            data.append(f'向量库块数：{vectordb.open_store().count()}')
        except Exception as e:
            data.append(f'向量库块数：读不到（{type(e).__name__}: {e}）')
        # 产物完整性：半成品最常见的来源是精读中途被打断（踩坑 #61）。
        # 直接把「停在哪一步、要不要重花钱」写进报告 —— 用户不必再单独跑一个脚本。
        gaps = []
        for k in keys:
            miss, present = paths.missing_artifacts(k)
            if miss:
                gaps.append((k, miss, present))
        data.append(f'产物不全的文献：{len(gaps)} 篇')
        if gaps:
            try:
                import importlib.util
                _sp = importlib.util.spec_from_file_location(
                    'gapdiag', os.path.join(ROOT, 'host', 'doctor', 'artifact_gaps.py'))
                _m = importlib.util.module_from_spec(_sp)
                _sp.loader.exec_module(_m)
                judge = _m.diagnose
            except Exception:
                judge = lambda miss, present: ('产物不齐', '')
            for k, miss, present in gaps[:10]:
                stage, advice = judge(miss, present)
                data.append(f'  {k}  停在：{stage}')
                data.append(f'      有：{"、".join(present) or "（什么都没有）"}')
                data.append(f'      缺：{"、".join(miss)}')
                if advice:
                    data.append(f'      建议：{advice}')
            if len(gaps) > 10:
                data.append(f'  …还有 {len(gaps) - 10} 篇')
        out.append(_section('数据资产', '\n'.join(data)))
    except Exception as e:
        out.append(_section('数据资产', f'统计失败：{type(e).__name__}: {e}'))

    # ── 自启任务实况 ──
    out.append(_section('自启任务实况（运行端应有 4 个）', _run(
        ps("Get-ScheduledTask | Where-Object {$_.TaskName -in "
           "@('ZoteroLiteratureWatcher','OllamaService','ZoteroApp','LiteratureAutoSync')} "
           "| Select-Object TaskName,State | Format-Table -AutoSize | Out-String"),
        timeout=120)))

    # ── 相关进程 ──
    out.append(_section('相关进程', _run(
        ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='pythonw.exe' "
           "or Name='ollama.exe' or Name='zotero.exe'\" "
           "| Select-Object ProcessId,Name,CommandLine | Format-List | Out-String"),
        timeout=120)))

    # ── 日志尾巴 ──
    # 包没装好时读不到数据契约，退回到契约里写死的默认位置 ——
    # 这时候日志恰恰最该看，不能因为「读不到路径」就整段放弃。
    logdir = paths.LOGS if CORE_OK else os.path.join(ROOT, 'workflow_data', 'logs')  # paths-exempt: 兜底
    def _log(name):
        return (paths.log(name) if CORE_OK else os.path.join(logdir, name + '.log'))
    out.append(_section('watcher 日志（尾部）', _tail(_log('zotero_watcher'), 150)))
    out.append(_section('看门狗日志（尾部）', _tail(_log('watchdog'), 60)))
    out.append(_section('定时同步日志（尾部）', _tail(_log('auto_sync'), 60)))
    # 两个信号分开看 —— 这样「watcher 到底换成新代码没有」是**看得见**的：
    # 旧版只写心跳、不写进度，所以进度文件缺失就说明它还在跑旧代码。
    # 2026-08-27 正是因为看不见这一点，才没发现重启计划任务换不掉 watcher 进程。
    def _age(fname):
        f = os.path.join(logdir, fname)
        try:
            return time.time() - int(io.open(f, encoding='utf-8').read().strip())
        except Exception:
            return None
    alive, prog = _age('watcher_heartbeat.txt'), _age('watcher_progress.txt')
    beat = []
    if alive is None:
        beat.append('报活信号：缺失 —— watcher 没在跑，或刚被重启')
    else:
        beat.append(f'报活信号：{int(alive)} 秒前（正常应 < 300 秒）')
    if prog is None and alive is not None:
        # 报活有、进展没有 = 进程在跑，但跑的是旧代码（旧版不写进展信号）
        beat.append('进展信号：缺失')
        beat.append('  ⚠ 新版 watcher 才写这个信号 —— 缺失说明它**还在跑旧代码**。')
        beat.append('    旧代码在精读期间不报活，会被看门狗中途杀掉（踩坑 #61）。')
        beat.append('    双击「更新平台.bat」会把它换成新代码。')
    elif prog is None:
        beat.append('进展信号：缺失（watcher 本来就没在跑）')
    else:
        beat.append(f'进展信号：{int(prog)} 秒前（超过 2700 秒才算异常；'
                    f'正在精读一篇时这个数会一直涨，属正常）')
        beat.append('  ✓ watcher 跑的是新代码（会分别报「活着」和「有进展」）')
    out.append(_section('精读监听的两个信号', chr(10).join(beat)))

    out.append(f'\n{SEP}\n报告结束。把整份内容发给 Claude 即可。\n{SEP}')
    return '\n'.join(out)


def main():
    if CORE_OK:
        dest = opt('--out') or paths.log('诊断报告', create_dir=True).replace('.log', '.txt')
    else:
        # 包没装好时也得把报告落盘，否则用户没东西可发给 Claude
        d = os.path.join(ROOT, 'workflow_data', 'logs')   # paths-exempt: 包没装好时的兜底
        os.makedirs(d, exist_ok=True)
        dest = opt('--out') or os.path.join(d, '诊断报告.txt')
    print('正在收集…（完整体检要跑一会儿，请稍候）\n', flush=True)
    text = collect()
    io.open(dest, 'w', encoding='utf-8', newline='').write(text)
    print(text[:2000])
    print(f'\n…（完整内容已写入）\n\n报告文件：{dest}')
    # 放进剪贴板，用户直接粘给 Claude。
    #
    # ⚠ 不能用 `clip`：它按**当前控制台代码页**（中文 Windows 上是 GBK）读 stdin，
    #   我们喂 UTF-8 进去，出来就是「鏍囪...」那种乱码（2026-08-27 实测复现）。
    #   走 PowerShell 读回刚写好的 UTF-8 文件再 Set-Clipboard，全程 Unicode，不丢字。
    quoted = dest.replace("'", "''")
    copied = False
    try:
        r = subprocess.run(
            ps("Get-Content -LiteralPath '" + quoted + "' -Encoding UTF8 -Raw "
               "| Set-Clipboard"),
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=60, creationflags=_NOWIN)
        copied = (r.returncode == 0)
    except Exception:
        pass
    if copied:
        print('（已复制到剪贴板，可以直接粘贴给 Claude）')
    else:
        print('（复制到剪贴板失败 —— 请手动打开上面那个文件，全选复制）')
    print('')
    print('把整份报告发给 Claude 即可 —— 它看不见这台机器，只能靠这份报告。')

    return 0


if __name__ == '__main__':
    sys.exit(main())
