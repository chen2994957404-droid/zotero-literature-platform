# -*- coding: utf-8 -*-
"""chart_digitize 自测：用本地 qwen2.5vl（零成本）+ 一张已解析文献的图，验证 digitize 结构。
用法: python pipelines/chart_digitize/selftest.py
需本地 Ollama 有 qwen2.5vl:7b，且 library 下有已解析文献。
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.domain.figure_crop import crop_figures
from pipelines.chart_digitize import digitize
from shared.kernel import paths

def main():
    lib = paths.LIBRARY
    parsed = None
    if os.path.isdir(lib):
        for k in os.listdir(lib):
            if os.path.exists(os.path.join(lib, k, 'parsed', 'layout.json')):
                parsed = os.path.join(lib, k, 'parsed'); break
    if not parsed:
        print('  [SKIP] 无已解析文献，无法测（非失败）'); sys.exit(0)

    figs = crop_figures(parsed)
    if not figs:
        print('  [SKIP] 该文献无可裁图（非失败）'); sys.exit(0)

    r = digitize(figs[min(1, len(figs)-1)]['b64'], provider='ollama', model='qwen2.5vl:7b')
    if 'error' in r:
        print(f'  [FAIL] 数字化出错: {r["error"]}'); sys.exit(1)
    # 结构检查：应有 chart_type 和 series（list）
    if 'chart_type' in r and isinstance(r.get('series'), list):
        print(f'  [PASS] 返回结构正确: chart_type={r.get("chart_type")}, '
              f'{len(r["series"])} 个系列')
        sys.exit(0)
    else:
        print(f'  [FAIL] 结构异常: {list(r.keys())}'); sys.exit(1)

if __name__ == '__main__':
    main()
