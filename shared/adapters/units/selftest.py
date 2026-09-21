# -*- coding: utf-8 -*-
"""units 自测：不联网、不读盘。Pint 装没装、论文里的单位写法认不认、量纲比对准不准。"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.adapters.units import dimension, same_dimension, to_base, normalize_unit


def main():
    ok = 0
    total = 5
    if normalize_unit('MJ m-3') == 'MJ*m**-3' and normalize_unit('°C') == 'degC' and normalize_unit('cm-1') == 'cm**-1':
        print('  [PASS] 论文写法 → Pint 写法'); ok += 1
    else:
        print('  [FAIL] normalize_unit', normalize_unit('MJ m-3'), normalize_unit('°C'))
    if same_dimension('MPa', 'kPa') and same_dimension('MJ m-3', 'kJ/m^3') and not same_dimension('MPa', 'mm'):
        print('  [PASS] 同量纲比对：MPa~kPa、MJ/m³~kJ/m³、MPa≠mm'); ok += 1
    else:
        print('  [FAIL] same_dimension')
    if dimension('kcal/mol') == dimension('kJ mol-1') and dimension('mV K-1') and dimension('cd m-2') and dimension('S/cm'):
        print('  [PASS] 冷门单位都认：kcal/mol、mV/K、cd/m²、S/cm'); ok += 1
    else:
        print('  [FAIL] dimension 冷门单位')
    if dimension('wt%') == 'dimensionless' and dimension('-fold') == 'dimensionless' and dimension('') == '' and dimension('xyzzy') == '':
        print('  [PASS] wt% / -fold 无量纲；空与乱码返回空'); ok += 1
    else:
        print('  [FAIL] 无量纲 / 空', dimension('wt%'), dimension('-fold'), dimension('xyzzy'))
    tb = to_base(1, 'MPa')
    if tb and abs(tb[0] - 1e6) < 1:
        print('  [PASS] 换算到基本单位：1 MPa = 1e6 Pa'); ok += 1
    else:
        print('  [FAIL] to_base', tb)
    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
