# -*- coding: utf-8 -*-
"""`python -m tools.extract` → cli.main()。真正的入口在 cli.py（R4 窗统一成这个形状）。"""
import sys

from tools.extract.cli import main

if __name__ == '__main__':
    sys.exit(main())
