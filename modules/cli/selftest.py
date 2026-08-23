# -*- coding: utf-8 -*-
"""cli 积木自测：把 sys.argv 换掉跑六组用例，全过即算数。"""
import os, sys

# 【标准开头】项目根加入 import 路径 + 强制 UTF-8 输出（详见 docs/代码规范_标准脚本模板.md）
_ROOT = os.path.dirname(os.path.abspath(__file__))
while True:
    if os.path.isdir(os.path.join(_ROOT, 'modules')):
        break                      # 项目根特征：modules/ 目录只在根存在
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        break                      # 到盘符根，兜底
    _ROOT = parent
sys.path.insert(0, _ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from modules import cli


def _run(argv, cases):
    """把 sys.argv 换成 argv，逐个跑 cases 里的 (说明, 函数, 期望值)。"""
    sys.argv = ['x'] + argv
    for label, fn, expect in cases:
        got = fn()
        assert got == expect, f'{label} {argv!r}: 应为 {expect!r}，实得 {got!r}'
    return True


def main():
    ok = 0
    # 1. 纯位置参数
    ok += _run(['polyborosiloxane', '8'], [
        ('pos(0)', lambda: cli.pos(0), 'polyborosiloxane'),
        ('pos(1)', lambda: cli.pos(1), '8'),
        ('pos(2) 缺省', lambda: cli.pos(2), None),
        ('positionals', lambda: cli.positionals(), ['polyborosiloxane', '8']),
        ('flag 不存在', lambda: cli.flag('--rebuild'), False),
    ])
    # 2. 选项 + 位置参数混用（位置参数在后面）
    ok += _run(['--limit', '20', 'query'], [
        ('pos 跳过选项', lambda: cli.pos(0), 'query'),
        ('opt(--limit)', lambda: cli.opt('--limit'), '20'),
        ('flag(--limit)', lambda: cli.flag('--limit'), True),
    ])
    # 3. 可重复选项
    ok += _run(['--tag', 'a', '--tag', 'b'], [
        ('opts(--tag)', lambda: cli.opts('--tag'), ['a', 'b']),
        ('positionals 为空', lambda: cli.positionals(), []),
    ])
    # 4. 纯开关
    ok += _run(['--rebuild'], [
        ('flag(--rebuild)', lambda: cli.flag('--rebuild'), True),
        ('positionals 为空', lambda: cli.positionals(), []),
    ])
    # 5. 位置参数当模式用（apply）
    ok += _run(['apply'], [
        ('pos(0)=apply', lambda: cli.pos(0), 'apply'),
    ])
    # 6. 选项在末尾没跟值 → 返回缺省
    ok += _run(['--limit'], [
        ('opt 末尾无值', lambda: cli.opt('--limit'), None),
        ('opt 自定义缺省', lambda: cli.opt('--limit', '8'), '8'),
    ])
    print(f'cli 自测 6 组全过（共 {ok} 组断言）。')


if __name__ == '__main__':
    main()
