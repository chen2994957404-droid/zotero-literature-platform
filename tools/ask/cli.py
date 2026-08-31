# -*- coding: utf-8 -*-
"""库内问答的命令行入口。

用法:
    python -m tools.ask "我的库里关于剪切增稠有什么"
    python -m tools.ask                进入交互模式，连续提问
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel.cli import positionals, wants_help
from tools import ask as _ask


def main():
    """有参数直接提问；无参数进交互模式。"""
    if wants_help():
        print(__doc__ or main.__doc__)
        return 0
    print(f'向量库共 {_ask.count()} 个文本块\n')
    args = positionals()
    if args:
        _ask.ask(' '.join(args))
        return
    print('进入问答模式（输入问题，回车提问；输入 q 退出）')
    while True:
        try:
            q = input('\n问> ').strip()
        except EOFError:
            break
        if q.lower() in ('q', 'quit', 'exit', ''):
            break
        try:
            _ask.ask(q)
        except Exception as e:
            # 单条问题失败只提示不退出：交互模式下用户可继续问下一条
            print('出错：', e)


if __name__ == '__main__':
    main()
