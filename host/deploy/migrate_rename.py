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
import shutil
import subprocess

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
    """把 remote-machine / toolforge 搬进 <root>/toolbox/。

    它们各自是独立的 git 仓库（有自己的 GitHub），搬进来只是**放在一起**，
    不合并版本库 —— 父仓库的 .gitignore 里已经把 toolbox/ 挡掉了。
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
        fail(lab, f'改不动：{e}\n      （多半是还有程序占着这个文件夹 —— '
                  f'关掉 Claude Code、编辑器、命令行窗口再试）')
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
    s1_toolbox(root)
    if s2_rename() or os.path.isdir(NEW_ROOT):
        s3_memory()
        s4_global_skills()
        s5_machines_toml()
        s6_reinstall()

    print('\n' + '=' * 62)
    print(f'  完成 {len(_done)} 步，跳过 {len(_skip)} 步，失败 {len(_fail)} 步')
    print('=' * 62)
    for f in _fail:
        print('  ❌ ' + f)

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

  4. B 机这次没动，还是老路径老名字，照常工作。
     等第二步（搬 tools/ 那四条线）时再一起处理。
""")
    return 1 if _fail else 0


if __name__ == '__main__':
    sys.exit(main())
