# -*- coding: utf-8 -*-
"""sentences 自测：缩写不切、位置对得上、按位置找句。纯本地、不联网。"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.adapters.sentences import split, sentence_at


def main():
    ok, total = 0, 3
    t = 'We heated PDMS at 180 °C for 2 h (Fig. 1a). The modulus was 4.1 MPa (ref. 5). Smith et al. reached 3 MPa vs. 2.5 MPa.'
    ss = split(t)
    if len(ss) == 3 and ss[1][2].startswith('The modulus'):
        print('  [PASS] Fig. / ref. / et al. / vs. 不当句尾'); ok += 1
    else:
        print('  [FAIL] split', [s[2] for s in ss])
    if all(t[s:e].strip() == sent for s, e, sent in ss):
        print('  [PASS] 位置与原文对得上'); ok += 1
    else:
        print('  [FAIL] 位置')
    if sentence_at(t, t.index('4.1')).startswith('The modulus') and sentence_at('a\n\nb c. d e.\n\nf', 5) == 'b c.':
        print('  [PASS] 按位置找句（跨段只切本段）'); ok += 1
    else:
        print('  [FAIL] sentence_at', repr(sentence_at(t, t.index('4.1'))), repr(sentence_at('a\n\nb c. d e.\n\nf', 5)))
    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
