# -*- coding: utf-8 -*-
"""ner 自测：噪声过滤是纯逻辑；真加载模型要 --live（第一次会下载 1 GB，且慢）。"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.kernel.cli import flag
from shared.adapters import ner


def main():
    ok, total = 0, 2
    if ner._NOISE.match('99%') and ner._NOISE.match('Gelest') and not ner._NOISE.match('PBS-1') and not ner._NOISE.match('PVA/CPO eutectogel'):
        print('  [PASS] 噪声过滤：供应商名 / 纯数字剔掉，样品名留下'); ok += 1
    else:
        print('  [FAIL] 噪声过滤')
    if flag('--live'):
        ms = ner.sample_mentions('The strength of FC-EtFe was 5.1 times that of FC-Et (1.40 MPa). PDMS (Gelest) was used.')
        if 'FC-EtFe' in ms and 'FC-Et' in ms and 'Gelest' not in ms:
            print('  [PASS] 真模型：认出 FC-EtFe / FC-Et，剔掉 Gelest'); ok += 1
        else:
            print('  [FAIL] 真模型', ms)
    else:
        print('  [SKIP] 真模型加载（加 --live）'); ok += 1
    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
