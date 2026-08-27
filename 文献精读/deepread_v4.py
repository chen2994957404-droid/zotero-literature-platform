# -*- coding: utf-8 -*-
"""精读 v4 的命令行入口 —— **逻辑已搬进 `pipelines/deepread/main_text.py`**。

用法: python deepread_v4.py <mineru_output_dir> <out.html> <provider> <model> [key]

为什么只剩这么薄（阶段 3，2026-08-27）：
    这个脚本原来是 180 行流水线，被 watcher / deepread_batch / rerun_pro
    三处用 subprocess 拉起来，接口就是「参数的先后顺序」。
    现在流水线是 `pipelines.deepread.main_text.read_main()` —— 能直接调、
    能直接测、能被状态库记账。本文件只负责把命令行参数翻译成那次函数调用，
    好让老的 .bat 与批量脚本一行不改照常能用。

新代码请直接调函数，别再拉子进程：
    from pipelines.deepread.main_text import read_main
"""
import sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from core.cli import pos
from pipelines.deepread.main_text import read_main, DeepreadFailed


def main():
    mo_dir, out_html, provider, model = pos(0), pos(1), pos(2), pos(3)
    if not (mo_dir and out_html):
        print(__doc__)
        raise SystemExit(2)
    try:
        read_main(mo_dir, out_html, provider=provider or 'deepseek',
                  model=model or 'deepseek-v4-flash', key=pos(4) or '')
    except DeepreadFailed as e:
        # 退出码非 0 = 调用方（watcher / 批量脚本）据此知道「别标成已精读」
        raise SystemExit(f'[FAIL] {e}')


if __name__ == '__main__':
    main()
