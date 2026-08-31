# -*- coding: utf-8 -*-
"""cli 积木自测：把 sys.argv 换掉跑六组用例，全过即算数。"""
import os, sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import cli


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
    # 2. 位置参数在前 + 选项在后（标准用法）
    ok += _run(['query', '8', '--limit', '20'], [
        ('pos(0)', lambda: cli.pos(0), 'query'),
        ('pos(1)', lambda: cli.pos(1), '8'),
        ('opt(--limit)', lambda: cli.opt('--limit'), '20'),
        ('flag(--limit)', lambda: cli.flag('--limit'), True),
        ('positionals', lambda: cli.positionals(), ['query', '8']),
    ])
    # 2b. 选项在前时，位置参数视为不存在（约定：位置参数必须在 -- 之前）
    ok += _run(['--limit', '20', 'query'], [
        ('pos 在选项后', lambda: cli.pos(0), None),
        ('positionals 为空', lambda: cli.positionals(), []),
        ('opt(--limit)', lambda: cli.opt('--limit'), '20'),
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
