# -*- coding: utf-8 -*-
"""stopwords 自测：词表完整（318 词，原样收录）、含 Pint 会误认成单位的那几个英文词。"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.domain.stopwords import ENGLISH_STOP_WORDS as S


def main():
    ok = len(S) == 318 and {'in', 'a', 'as', 'at', 'are', 'am', 'de', 'has', 'he', 'me', 're', 'us'} <= S and 'polymer' not in S
    print('  [%s] 318 词、含 Pint 误认的 12 个、不含领域词' % ('PASS' if ok else 'FAIL'))
    print()
    print('%d/1 通过' % (1 if ok else 0))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
