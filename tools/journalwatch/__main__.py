# -*- coding: utf-8 -*-
"""`python -m tools.journalwatch` → cli.main()。真正的入口在 cli.py。"""
import sys

from tools.journalwatch.cli import main

if __name__ == '__main__':
    sys.exit(main())
