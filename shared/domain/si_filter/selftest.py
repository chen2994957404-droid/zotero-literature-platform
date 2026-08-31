# -*- coding: utf-8 -*-
"""si_filter 自测：验证 SI 噪声过滤——该丢的丢、**关键信息绝不误杀**。
用法: python shared/domain/si_filter/selftest.py

重点测"不误杀"：曾因正则过粗把 `Mw = 4200 g/mol`、¹¹B NMR、公式段当作者名单丢掉（踩坑）。
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from shared.domain.si_filter import classify, filtered_text, stats

SAMPLE = """# A novel material derived from diboron structures

Qi Wu $^{1}$ , Yan Peng $^{1,3}$ , Hui Xiong $^{1}$

$^{1}$ . College of Polymer Science and Engineering, Sichuan University

Supporting Information

Figures S1-S23

## Materials

Hydroxyl-terminated poly(dimethylsiloxane) (PDMS-OH, Mw = 4200 g/mol) was provided by Gelest Inc.

## Synthesis

Typically, PDMS-OH (5 g, 1.19 mmol), DBA (0.058 g, 0.655 mmol) and DMSO/IPA solvent
(2 mL, v/v = 4: 1) were mixed and stirred at room temperature for 6 h.

Proton nuclear magnetic resonance ( $^{1}$ H NMR): spectra were recorded on a Bruker 400 MHz.

$^{1}$ $\\Delta E(bond)=E(total)-E(part1)-E(part2)$

## Reference

1. Kresse, G.; Furthmuller, J., Phys. Rev. B 1996.
"""


def main():
    ok = total = 0
    ft = filtered_text(SAMPLE)

    # 1. 关键信息绝不丢（最重要）
    must_keep = ['Mw = 4200', '1.19 mmol', '0.655 mmol', 'v/v = 4: 1', '6 h']
    total += 1
    lost = [k for k in must_keep if k not in ft]
    if not lost:
        print('  [PASS] 关键信息全部保留（分子量/投料量/配比/时间）'); ok += 1
    else:
        print(f'  [FAIL] 误杀关键信息: {lost}')

    # 2. 纯元信息该丢
    must_drop = ['College of Polymer Science', 'Figures S1-S23', 'Kresse, G.']
    total += 1
    kept_junk = [k for k in must_drop if k in ft]
    if not kept_junk:
        print('  [PASS] 元信息（单位/目录/参考文献）已滤除'); ok += 1
    else:
        print(f'  [FAIL] 噪声未滤除: {kept_junk}')

    # 3. 含上标的科学内容不被当作者名单丢掉（踩坑回归测试）
    total += 1
    if 'NMR' in ft or 'Delta E' in ft or 'H NMR' in ft:
        print('  [PASS] 含上标的科学内容未被误判为作者行'); ok += 1
    else:
        print('  [FAIL] 含上标的科学内容被误杀（正则过粗）')

    # 4. 分档统计可用
    total += 1
    s = stats(SAMPLE)
    if s['counts'].get('core', 0) > 0 and s['counts'].get('drop', 0) > 0:
        print(f'  [PASS] 分档正常: {s["counts"]}'); ok += 1
    else:
        print(f'  [FAIL] 分档异常: {s["counts"]}')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
