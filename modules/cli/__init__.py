# -*- coding: utf-8 -*-
"""cli · 命令行参数解析基础件（公理：全项目只有一种取参数的方式）

解决的真实问题（2026-08-11 体检）：79 个 .py 里有 97 处手写 sys.argv，
风格至少 10 种（'--flag' in sys.argv / sys.argv.index('--tag')+1 / 位置切片 / 列表推导去 -- …）。
每份脚本各写各的，AI 接手每看一个文件都要重新学习。收敛到这里后，任何脚本的参数写法都是同一套。

设计原则：
  - 只读 sys.argv，不用 argparse —— 本项目参数都很简单（几个位置参数 + 几个 --开关），
    argparse 的 help/子命令等重装备用不上，反而引入一套新语法（符合宪法判据：能自己做的稳定部分自己做）
  - 取不到参数返回默认值，**绝不抛异常** —— 缺参时由脚本业务逻辑自己判断（很多脚本允许无参运行）

用法：
    from modules.cli import pos, flag, opt, opts, positionals
    query = pos(0)                     # python find_papers.py "polyborosiloxane"  → 'polyborosiloxane'
    limit = int(pos(1) or 8)           # python find_papers.py q 20                  → 20
    rebuild = flag('--rebuild')        # python vectorize.py --rebuild               → True
    top = int(opt('--top', '10'))      # python ask_world.py --top 5                 → 5
    tags = opts('--tag')               # python import_by_doi.py --tag a --tag b     → ['a','b']
"""
import sys


def _argv():
    """去掉程序名后的全部参数。"""
    return sys.argv[1:]


def positionals():
    """所有位置参数（不以 -- 开头的参数），按出现顺序。"""
    return [a for a in _argv() if not a.startswith('--')]


def pos(index, default=None):
    """第 index 个位置参数（从 0 开始，自动跳过 -- 开头的）。没有就返回 default。"""
    args = positionals()
    return args[index] if index < len(args) else default


def flag(name, default=False):
    """开关参数：命令行里出现 --名字 即返回 True，否则 default。"""
    return name in _argv()


def opt(name, default=None):
    """带值参数：取 --名字 后面紧跟的那个值。参数不存在返回 default。"""
    args = _argv()
    if name in args:
        i = args.index(name)
        if i + 1 < len(args) and not args[i + 1].startswith('--'):
            return args[i + 1]
    return default


def opts(name):
    """带值参数（可重复）：--名字 每次出现取后面一个值，收集成列表。"""
    values = []
    args = _argv()
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args) and not args[i + 1].startswith('--'):
            values.append(args[i + 1])
    return values
