# -*- coding: utf-8 -*-
"""SI（补充材料）精读的命令行入口 —— **逻辑已搬进 `pipelines/deepread/si.py`**。

用法：python si_deepread.py <ZoteroKey> [out.html]

价值（不变）：SI 含正文完全没有的可复现细节 —— 精确投料量、原料分子量、
溶剂配比、各复合材料制备克数、对照组设计逻辑。
正文精读 = 理解这篇做了什么；SI 精读 = 我要复现时查参数。

搬家原因见 `pipelines/deepread/__init__.py`（阶段 3：不再靠 subprocess 串工作流）。
新代码直接调 `pipelines.deepread.si.read_si(key)`。
"""
import sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from core.cli import pos
from pipelines.deepread.si import read_si, SIFailed


def main():
    key = pos(0)
    if not key:
        print('用法: python si_deepread.py <ZoteroKey> [out.html]')
        sys.exit(1)
    try:
        out = read_si(key, out_html=pos(1))
    except SIFailed as e:
        print(f'[失败] {e}')
        sys.exit(1)
    if not out:
        sys.exit(0)          # 没有 SI 附件不是失败


if __name__ == '__main__':
    main()
