# -*- coding: utf-8 -*-
"""把这份技能装到「所有项目都能用」的位置。

    python install.py            装 / 更新
    python install.py --check    只看装没装、是不是最新（不写盘）

装到 `~/.claude/skills/toolforge/SKILL.md`。那个位置的技能对**每个**项目都生效 ——
这正是把工具单独拆出来的意义：它跟任何具体项目都无关。

装的时候会把技能里的路径换成**这个仓库的真实位置**，所以仓库搬了家重跑一次即可。
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
DEST_DIR = os.path.join(os.path.expanduser('~'), '.claude', 'skills', 'toolforge')
DEST = os.path.join(DEST_DIR, 'SKILL.md')

# 技能源里写的是作者机器上的路径；装的时候换成真实路径
PLACEHOLDER = 'D:/dev/toolforge'


def rendered():
    return io.open(SRC, encoding='utf-8').read().replace(
        PLACEHOLDER, REPO.replace('\\', '/'))


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
    return 0


if __name__ == '__main__':
    sys.exit(main())
