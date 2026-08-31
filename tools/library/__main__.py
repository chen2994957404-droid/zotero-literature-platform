# -*- coding: utf-8 -*-
"""`python -m tools.library <动作>` = 查我的 Zotero 库（用法见 cli.py）。"""
import sys

from tools.library.cli import main

if __name__ == '__main__':
    sys.exit(main())
