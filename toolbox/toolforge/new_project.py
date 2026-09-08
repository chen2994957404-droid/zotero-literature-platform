# -*- coding: utf-8 -*-
"""开一个新工具项目 —— 把每次都要重写的那堆东西一次性生出来。

    python new_project.py <名字> --desc "一句话说它干什么"
    python new_project.py getpdf --desc "一批 DOI 换正文 PDF" --dir D:/dev

生成（在 `<dir>/<名字>/`，默认 dir 是本仓库的上一级）：

    README.md          装两步 + 怎么用 + 边界，骨架已经写好，填内容即可
    LICENSE            MIT，版权人已填好（不填就会被 preflight 拦下）
    .gitignore         默认挡住配置与密钥
    <名字>.py          入口脚本（名字里的横杠会换成下划线，否则 import 不了）
    config.example.toml
    install.py         把技能装到 ~/.claude/skills/，装完所有项目都能用
    skill/SKILL.md     给 agent 看的说明书（源）
    tests/test_smoke.py

**它不碰任何已有项目。** 拆分从今往后一律「复制不搬走」：
新项目里放一份自包含的副本，原项目原封不动照跑。

## 为什么值得有这个脚本

做 `remote-machine` 时上面这些全是现写的。第二个项目再写一遍，
两遍就会不一样 —— 而不一样的地方往往是**漏掉的那一项**（许可证没填、
配置没挡进 .gitignore、README 少了「怎么装」）。
骨架的价值不在省时间，在**不会漏**。
"""
import io
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, 'template')
_NL = chr(10)

# 版权人。改成你自己的名字/GitHub 用户名即可（留空会被 preflight 拦）。
OWNER = 'balabala-1314'

# 模板文件名 → 生成后的真名。`.gitignore` 不能直接放在模板目录里，
# 否则 git 会把模板目录里的文件也按它忽略掉 —— 所以存成 gitignore.txt。
RENAME = {'gitignore.txt': '.gitignore', 'entry.py': '{mod}.py'}


def opt(flag, default=''):
    a = sys.argv[1:]
    for i, x in enumerate(a):
        if x == flag and i + 1 < len(a):
            return a[i + 1]
        if x.startswith(flag + '='):
            return x.split('=', 1)[1]
    return default


def render(text, name, desc):
    # `remote-machine` 这种名字带横杠，**不能当模块名** —— 带横杠的 .py 
    # 文件 import 不进来，测试第一行就崩。所以入口文件名把横杠换成下划线。
    # preflight-ok 下面这几行就是占位符表本身
    return (text.replace('{{NAME_MOD}}', name.replace('-', '_'))  # preflight-ok
                .replace('{{ENV_PREFIX}}', name.replace('-', '_').upper())  # preflight-ok
                .replace('{{NAME}}', name)  # preflight-ok
                .replace('{{DESC}}', desc)  # preflight-ok
                .replace('{{OWNER}}', OWNER)  # preflight-ok
                .replace('{{YEAR}}', time.strftime('%Y'))  # preflight-ok
                .replace('{{DATE}}', time.strftime('%Y-%m-%d')))  # preflight-ok


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    if not args:
        print(__doc__)
        return 0
    name = args[0]
    desc = opt('--desc') or '（还没写一句话说明）'
    root = os.path.abspath(opt('--dir') or os.path.dirname(HERE))
    dest = os.path.join(root, name)

    if os.path.exists(dest):
        # 不覆盖。骨架覆盖真代码是那种「一秒钟毁掉一下午」的事故。
        print(f'{dest} 已经存在了 —— 不动它。'
              + _NL + '（要重来先自己删；这个脚本不覆盖任何东西。）')
        return 2

    made = []
    for cur, _dirs, files in os.walk(TEMPLATE):
        for f in files:
            src = os.path.join(cur, f)
            rel = os.path.relpath(src, TEMPLATE)
            out_rel = RENAME.get(f, f).format(name=name,
                                              mod=name.replace('-', '_'))
            out = os.path.join(dest, os.path.dirname(rel), out_rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            text = io.open(src, encoding='utf-8').read()
            with io.open(out, 'w', encoding='utf-8', newline='\n') as fh:
                fh.write(render(text, name, desc))
            made.append(os.path.relpath(out, dest))

    print(f'已生成 {dest}，{len(made)} 个文件：')
    for m in sorted(made):
        print('  ' + m)
    print(_NL + '接下来：')
    print(f'  1. 把要拆的代码**复制**进去（原项目别动），'
          f'跑通 {name.replace(chr(45), chr(95))}.py')
    print('  2. cd 进去：git init -b main && git add -A && git commit')
    print(f'  3. 发布前体检：python {os.path.join(HERE, "preflight.py")} '
          f'{dest} --tests')
    print('  4. 红的清零之后再建 GitHub 仓库、推上去')
    return 0


if __name__ == '__main__':
    sys.exit(main())
