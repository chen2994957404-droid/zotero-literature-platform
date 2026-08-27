# -*- coding: utf-8 -*-
"""zotero_client 自测：验证 find_pdf 对已知文献正确选中正文（非 SI）。
用法: python adapters/zotero_client/selftest.py
"""
import sys, os
from adapters.zotero_client import find_pdf

# 已知有正文的 key（CABSSMLA 是踩坑#15 那篇：SI 比正文大，考验判定）
CASES = ['CABSSMLA', 'BMJEJ4ZY', '2T6H4S3D']

def main():
    ok = 0
    for k in CASES:
        p = find_pdf(k)
        if p and 'moesm' not in p.lower() and '_esm' not in p.lower() and 'suppmat' not in p.lower():
            print(f'  [PASS] {k} → {os.path.basename(p)[:55]}'); ok += 1
        else:
            print(f'  [FAIL] {k} → {p}')
    print(f'\n{ok}/{len(CASES)} 通过')
    sys.exit(0 if ok == len(CASES) else 1)

if __name__ == '__main__':
    main()
