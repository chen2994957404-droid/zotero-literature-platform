# -*- coding: utf-8 -*-
"""把这份技能装到「所有项目都能用」的位置。

    python install.py            装 / 更新
    python install.py --check    只看装没装、装的是不是最新（不写盘）

装到哪：`~/.claude/skills/remote-machine/SKILL.md`。
那个位置的技能对**每个**项目都自动生效 —— 这正是把这套东西拆出来的理由：
「怎么操作另一台机器」跟任何具体项目都无关，不该只住在其中一个仓库里。

装的时候会把技能里的工具路径换成**这个仓库的真实位置**，
所以仓库搬了家，重跑一次 install.py 就行。
"""
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

REPO = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(REPO, 'skill', 'SKILL.md')
DEST_DIR = os.path.join(os.path.expanduser('~'), '.claude', 'skills', 'remote-machine')
DEST = os.path.join(DEST_DIR, 'SKILL.md')

# 源文件里写的是作者机器上的路径；装的时候换成真实路径。
PLACEHOLDER = 'D:/dev/remote-machine'


def rendered():
    text = io.open(SRC, encoding='utf-8').read()
    here = REPO.replace('\\', '/')
    return text.replace(PLACEHOLDER, here)


def main():
    want = rendered()
    have = io.open(DEST, encoding='utf-8').read() if os.path.isfile(DEST) else None

    if '--check' in sys.argv[1:]:
        if have is None:
            print(f'还没装。装到：{DEST}')
            return 1
        if have != want:
            print(f'装过了，但跟仓库里的不一样（重跑 install.py 更新）：{DEST}')
            return 1
        print(f'已装且是最新：{DEST}')
        return 0

    os.makedirs(DEST_DIR, exist_ok=True)
    with io.open(DEST, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(want)
    print(f'已装到 {DEST}')
    print('  → 之后在**任何**项目里开新会话，这份技能都在。')

    conf = os.path.join(os.path.expanduser('~'), '.remote-machine', 'machines.toml')
    if not os.path.isfile(conf):
        print(f'⚠ 还没有配置文件：{conf}')
        print('  照着仓库里的 machines.example.toml 抄一份过去，填上地址、账号、私钥路径。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
