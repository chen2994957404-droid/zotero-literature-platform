# -*- coding: utf-8 -*-
"""figure_crop 自测：用一篇已解析的文献验证能裁出完整 Figure。
用法: python modules/figure_crop/selftest.py
需 library 下有至少一篇含 parsed/layout.json 的文献。
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules.figure_crop import crop_figures
from core import paths

def main():
    lib = paths.LIBRARY
    # 找第一个有 parsed/layout.json 的文献
    target = None
    if os.path.isdir(lib):
        for k in os.listdir(lib):
            if os.path.exists(os.path.join(lib, k, 'parsed', 'layout.json')):
                target = os.path.join(lib, k, 'parsed'); break
    if not target:
        print('  [SKIP] library 下没有已解析文献，无法测（非失败）'); sys.exit(0)

    figs = crop_figures(target)
    if figs and all('b64' in f and f['b64'].startswith('data:image') for f in figs):
        print(f'  [PASS] 裁出 {len(figs)} 张完整图，每张有 b64 数据')
        print(f'         来源: {os.path.basename(os.path.dirname(target))}')
        sys.exit(0)
    else:
        print(f'  [FAIL] 裁图结果异常: {len(figs) if figs else 0} 张')
        sys.exit(1)

if __name__ == '__main__':
    main()
