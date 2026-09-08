# -*- coding: utf-8 -*-
"""一次性搬迁：zotero-literature-platform → literature-platform（第一步）

**为什么要有这个脚本**：改名要动的东西横跨「项目内 / 项目外 / Claude Code 自己的
记忆目录 / 全局技能 / B 机连接配置」五处，漏一处就是一个几天后才发现的怪问题。
写成脚本 = 一次做完、可复查、能重跑。

**为什么它要从 %TEMP% 跑**：它要改的目录就是它自己住的目录。Windows 不许你
重命名一个正被占用的目录，所以配套的 `launch/一次性_改名并重组.bat` 会先把
本文件复制到 %TEMP%，再从那里启动。

**为什么它不守那几条红线**（只依赖标准库、不走 shared.kernel.cli/log）：
它跑到一半时项目已经改了名，`pip install -e .` 注册的路径正处于失效状态，
这时候 `import shared.kernel.*` 必然失败。所以它只能是一个自给自足的独立脚本。
它不接任何参数，也就不存在「参数没认出来 → 走进最贵那条路」的风险（踩坑 #85）。

做完之后仍然要人手做的事，脚本最后会打印出来。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import io
import json
import shutil
import subprocess

_NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0

DEV = r'D:\dev'
OLD_NAME = 'zotero-literature-platform'
NEW_NAME = 'literature-platform'
OLD_ROOT = os.path.join(DEV, OLD_NAME)
NEW_ROOT = os.path.join(DEV, NEW_NAME)
HOME = os.path.expanduser('~')

# 要搬进 toolbox/ 的通用工具：跟文献无关、任何项目都能用
TOOLBOX_MOVES = ['remote-machine', 'toolforge']

_done, _skip, _fail = [], [], []


def step(label):
    """打印一步的标题，返回一个记录结果用的闭包。"""
    print('\n── ' + label)
    return label


def ok(label, msg):
    print('   ✅ ' + msg)
    _done.append(label)


def skip(label, msg):
    print('   ⏭  ' + msg)
    _skip.append(label)


def fail(label, msg):
    print('   ❌ ' + msg)
    _fail.append(f'{label}：{msg}')


def replace_in_file(path, pairs):
    """把 pairs 里的替换应用到一个文本文件。返回改了几处。"""
    if not os.path.exists(path):
        return None
    t = io.open(path, encoding='utf-8').read()
    n = sum(t.count(a) for a, _ in pairs)
    if n:
        for a, b in pairs:
            t = t.replace(a, b)
        io.open(path, 'w', encoding='utf-8', newline='').write(t)
    return n


def s1_toolbox(root):
    """核对 toolbox/ 到位了没。

    2026-09-08 用户拍板：**toolbox 并进主仓库的版本管理**，不再是两个独立仓库
    （理由：「单独弄还是不方便实时更新」—— 改一下就要切到另一个仓库去提交）。
    所以搬移已经在开发时做完并提交了，这里只剩核对。
    留着这一步是为了「万一没搬」也能自愈。它们原来的 git 历史在 GitHub 上还有。
    """
    lab = step('第 1 步：把通用工具搬进 toolbox/')
    box = os.path.join(root, 'toolbox')
    os.makedirs(box, exist_ok=True)
    moved = []
    for name in TOOLBOX_MOVES:
        src, dst = os.path.join(DEV, name), os.path.join(box, name)
        if os.path.exists(dst):
            print(f'   ⏭  {name} 已经在 toolbox/ 里了')
            continue
        if not os.path.isdir(src):
            fail(lab, f'找不到 {src}')
            continue
        shutil.move(src, dst)
        moved.append(name)
        print(f'   → {name} 搬好了')
    if moved:
        ok(lab, '搬进 toolbox/：' + '、'.join(moved))
    elif not _fail:
        skip(lab, '两个都已经在里面了')


def _all_procs():
    """问系统要一份进程清单（pid / 父 pid / 名字 / 命令行）。

    不用第三方库：走 PowerShell 的 CIM 查询，结果按 JSON 拿回来。
    查不到就返回空清单 —— 这一步是**帮忙**，查不动也不该挡住搬迁。
    """
    ps = ('Get-CimInstance Win32_Process | Select-Object '
          'ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress')
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=60, creationflags=_NOWIN)
        data = json.loads(r.stdout or '[]')
    except Exception:
        return []
    return data if isinstance(data, list) else [data]


def _blockers():
    """谁占着项目文件夹？返回 [(pid, 名字, 命令行)]。

    **判据是命令行里提到项目路径**：一个进程只要工作目录在文件夹里，
    Windows 就不让重命名这个文件夹，而工作目录是从启动它的 .bat 继承来的。

    典型元凶是 `pythonw.exe host/panel/launcher.py` —— 控制面板的后台进程。
    `pythonw` **没有窗口**，用户在任务栏上根本看不见它，
    所以「关掉 Claude Code 再试」这种提示对他毫无用处
    （2026-09-08 第一次真跑就栽在这上面，见踩坑 #146）。

    要排除「我自己这条线」：本脚本从 %TEMP% 跑，自己的命令行里没有项目路径，
    但启动它的那个 .bat 有 —— 所以把自己的**祖先进程**整条链剔掉。
    """
    procs = _all_procs()
    if not procs:
        return []
    parent = {p.get('ProcessId'): p.get('ParentProcessId') for p in procs}
    mine, pid = set(), os.getpid()
    while pid and pid not in mine:
        mine.add(pid)
        pid = parent.get(pid)

    key = OLD_NAME.lower()
    out = []
    for p in procs:
        cmd = p.get('CommandLine') or ''
        if key in cmd.lower() and p.get('ProcessId') not in mine:
            out.append((p['ProcessId'], p.get('Name') or '?', cmd))
    return out


# 平台自己的后台进程：可以放心停掉，用户随时能重新双击打开
_OURS = ('host\\panel', 'host/panel', 'host.panel',
         'host\\watcher', 'host/watcher', 'host.watcher')


def _friendly(name, cmd):
    """把进程翻译成用户认得出的东西。

    直接甩十行 `bash.exe` 给一个不懂编程的人 = 等于没说。
    他需要的是「哦，那是 Claude Code，我去关掉」。
    """
    low = (name + ' ' + cmd).lower()
    if 'shell-snapshots' in low or 'claude' in low:
        return 'Claude Code'
    if name.lower() in ('cmd.exe', 'powershell.exe', 'pwsh.exe',
                        'windowsterminal.exe', 'conhost.exe'):
        return '命令行窗口'
    if name.lower() in ('code.exe', 'devenv.exe', 'pycharm64.exe',
                        'sublime_text.exe', 'notepad++.exe'):
        return '编辑器'
    if name.lower() == 'explorer.exe':
        return '资源管理器（停在这个文件夹里的窗口）'
    return name


def s0_free_folder():
    """把占着项目文件夹的进程清掉，否则第 2 步的改名一定失败。"""
    lab = step('第 0 步：腾出文件夹（关掉占着它的后台程序）')
    blockers = _blockers()
    if not blockers:
        skip(lab, '没有程序占着，可以直接改名')
        return True

    ours, others = [], []
    for pid, name, cmd in blockers:
        (ours if any(k in cmd.lower() for k in _OURS) else others).append((pid, name, cmd))

    for pid, name, cmd in ours:
        which = '控制面板' if 'panel' in cmd.lower() else '精读监听'
        print(f'   → 停掉平台自己的后台进程：{name} (pid {pid}，{which})')
        subprocess.run(['taskkill', '/PID', str(pid), '/F', '/T'],
                       capture_output=True, creationflags=_NOWIN)

    if others:
        # 按「用户认得出的名字」归并，而不是一行一个进程
        groups = {}
        for pid, name, cmd in others:
            groups.setdefault(_friendly(name, cmd), []).append(pid)
        print('\n   ⚠ 下面这些还占着项目文件夹，我不敢替你关 ——'
              '\n     请你自己关掉它们，然后再双击一次本文件：\n')
        for label, pids in sorted(groups.items()):
            n = f'（{len(pids)} 个进程）' if len(pids) > 1 else ''
            print(f'      ● {label}{n}')
        fail(lab, f'还有 {len(groups)} 类程序占着文件夹，没法改名')
        return False

    ok(lab, f'停掉了 {len(ours)} 个平台自己的后台进程')
    return True


def s2_rename():
    """把项目文件夹改名。"""
    lab = step('第 2 步：文件夹改名')
    if os.path.isdir(NEW_ROOT):
        skip(lab, f'{NEW_ROOT} 已经存在，跳过')
        return True
    if not os.path.isdir(OLD_ROOT):
        fail(lab, f'找不到 {OLD_ROOT}，也没有 {NEW_ROOT}')
        return False
    try:
        os.rename(OLD_ROOT, NEW_ROOT)
    except OSError as e:
        # 别再说「多半是有程序占着」—— 用户看不见一个没有窗口的进程，
        # 这种提示等于没提示（踩坑 #146）。把真凶的名字列出来。
        names = [f'pid {p} {n}' for p, n, _ in _blockers()]
        if names:
            hint = '还占着它的是：' + '、'.join(names)
        else:
            hint = ('没查到是谁占着 —— 也可能是杀毒软件或资源管理器正在扫这个文件夹，'
                    '等十几秒再双击一次本文件试试')
        fail(lab, f'改不动：{e}\n      {hint}')
        return False
    ok(lab, f'{OLD_NAME} → {NEW_NAME}')
    return True


def s3_memory():
    """把 Claude Code 的记忆搬到新项目名下。

    Claude Code 按**文件夹路径**存记忆和聊天历史，改名后它会认成一个新项目。
    这里是复制不是移动 —— 旧的留着，万一要回头查。
    """
    lab = step('第 3 步：把 Claude Code 的记忆搬到新名字下')
    base = os.path.join(HOME, '.claude', 'projects')
    src = os.path.join(base, 'D--dev-' + OLD_NAME)
    dst = os.path.join(base, 'D--dev-' + NEW_NAME)
    if not os.path.isdir(src):
        skip(lab, f'没有旧记忆目录（{src}）')
        return
    if os.path.isdir(dst):
        skip(lab, '新记忆目录已存在，没覆盖')
        return
    shutil.copytree(src, dst)
    ok(lab, f'记忆已复制到 {os.path.basename(dst)}（旧的保留着）')


def s4_global_skills():
    """全局技能里写死的绝对路径要指到新位置。

    这两份技能是**全局**的（任何项目都能用），所以只能写绝对路径。
    """
    lab = step('第 4 步：改全局技能里写死的路径')
    total = 0
    for name in TOOLBOX_MOVES:
        p = os.path.join(HOME, '.claude', 'skills', name, 'SKILL.md')
        n = replace_in_file(p, [
            # 技能里已经指向 toolbox/，只是项目文件夹名要换
            (f'D:/dev/{OLD_NAME}/', f'D:/dev/{NEW_NAME}/'),
            # 兜底：万一还是搬进 toolbox 之前的老写法
            (f'D:/dev/{name}/', f'D:/dev/{NEW_NAME}/toolbox/{name}/'),
        ])
        if n is None:
            print(f'   ⏭  没装全局技能 {name}')
        else:
            print(f'   → {name}/SKILL.md 改了 {n} 处')
            total += n
    ok(lab, f'共改 {total} 处') if total else skip(lab, '没有要改的')


def s5_machines_toml():
    """B 机连接配置里的 local 路径（A 机这边的项目位置）。

    ⚠ 只改 local。`root`（B 机上的路径）**故意不动** ——
    第一步不碰 B 机，那边 4 个开机自启任务还指着老路径。
    """
    lab = step('第 5 步：改 B 机连接配置里的 A 机路径')
    p = os.path.join(HOME, '.remote-machine', 'machines.toml')
    n = replace_in_file(p, [(f'D:/dev/{OLD_NAME}', f'D:/dev/{NEW_NAME}')])
    if n is None:
        skip(lab, '没有 machines.toml')
    elif n == 0:
        skip(lab, '里面没有旧路径（可能已经改过）')
    else:
        ok(lab, f'local 路径已更新（B 机的 root 故意没动）')


def s6_reinstall():
    """包名改了，要重新注册一次，否则所有 import 都会指向不存在的旧路径。"""
    lab = step('第 6 步：重新把项目装成 Python 包')
    if not os.path.isdir(NEW_ROOT):
        fail(lab, '新目录不存在，跳过')
        return
    cmd = [sys.executable, '-m', 'pip', 'install', '-e', '.', '--no-deps']
    print('   跑：' + ' '.join(cmd))
    # 显式带 creationflags 防弹窗 —— 本该走 shared.kernel.subproc，
    # 但本脚本必须自给自足（见文件头），所以这里自己写一份等价的。
    no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
    r = subprocess.run(cmd, cwd=NEW_ROOT, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', creationflags=no_window)
    if r.returncode == 0:
        ok(lab, '装好了')
    else:
        fail(lab, '装失败，输出如下：\n' + (r.stdout or '') + (r.stderr or ''))


def main():
    print('=' * 62)
    print('  一次性搬迁：zotero-literature-platform → literature-platform')
    print('=' * 62)
    print('\n这一步只动 A 机（你现在这台）。B 机完全不受影响。')

    root = NEW_ROOT if os.path.isdir(NEW_ROOT) else OLD_ROOT
    # 先腾文件夹再干别的 —— 腾不出来就别去撞改名，那只会再抱怨一遍同样的话
    freed = s0_free_folder() or os.path.isdir(NEW_ROOT)
    s1_toolbox(root)
    if freed and (s2_rename() or os.path.isdir(NEW_ROOT)):
        s3_memory()
        s4_global_skills()
        s5_machines_toml()
        s6_reinstall()

    print('\n' + '=' * 62)
    print(f'  完成 {len(_done)} 步，跳过 {len(_skip)} 步，失败 {len(_fail)} 步')
    print('=' * 62)
    for f in _fail:
        print('  ❌ ' + f)

    if _fail:
        # 失败时**别**打印后续清单：那会叫用户去打开一个还不存在的新文件夹。
        # 什么都没改坏，把这句说清楚比什么都重要。
        print("""
   这次什么都没有改动 —— 项目还在原来的位置，一切照旧。
   按上面说的把占着文件夹的程序关掉，再双击一次本文件就行。
""")
        return 1

    print("""
接下来还要你自己做的（脚本碰不了的）：

  1. 用 Claude Code 打开新文件夹  D:\\dev\\literature-platform
     （旧路径已经不存在了，书签/快捷方式要重指一下）

  2. 打开一次控制面板确认平台还好：双击 launch\\控制面板.bat
     或者跑一次体检：  python host\\doctor\\health_check.py

  3. GitHub 上的仓库名要不要改，你自己定 —— 不改也完全不影响使用。
     要改的话在 GitHub 网页上改，然后回来跑：
       git remote set-url origin  <新地址>
       git remote set-url backup  <新地址>

  4. 刚才如果停掉了控制面板的后台进程，重新双击一次
     launch\\控制面板.bat 就回来了（不用管，用到再开）。

  5. B 机这次没动，还是老路径老名字，照常工作。
     等第二步（搬 tools/ 那四条线）时再一起处理。
""")
    return 0


if __name__ == '__main__':
    sys.exit(main())
