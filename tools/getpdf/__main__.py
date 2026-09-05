# -*- coding: utf-8 -*-
"""`python -m tools.getpdf <DOI...>` = 把这些文献的正文 PDF 取到手（用法见 cli.py）。"""
import sys

from tools.getpdf.cli import main

if __name__ == '__main__':
    sys.exit(main())
