# -*- coding: utf-8 -*-
"""numcheck 自测：纯逻辑，不联网、不碰用户数据。

测的是三条承诺：
  ① 列清单认得出带单位的数、千分位、年份不算、按出现顺序去重
  ② 查覆盖只比数值不比单位（单位常被译成中文），0.50 与 0.5 算同一个
  ③ 查来源：产出里有、来源里没有的数报出来；图号/年份/单个位数不报
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.domain.numcheck import checklist_block, missing_numbers, must_numbers, unverified_numbers

_fail = []


def check(name, cond, extra=''):
    print(('  [PASS] ' if cond else '  [FAIL] ') + name + (('  ' + extra) if extra else ''))
    if not cond:
        _fail.append(name)


def main():
    print('numcheck 自测')
    must = must_numbers('droplets 19 μm, 46 μm (Fig. 2b); strain 1160% and 200 %; Tg 25 °C in 2024; Mn 1,500 g/mol; 0.50 MPa')
    check('列清单', must == ['19 μm', '46 μm', '1160 %', '200 %', '25 °C', '1,500 g/mol', '0.50 MPa'], str(must))
    check('清单上限', len(must_numbers('1 %, ' * 50, cap=5)) == 1)         # 同一个数不重复
    miss = missing_numbers('液滴 19 微米与 46 μm，应变 1160%，Tg 25 ℃，Mn 1500 g/mol，0.5 MPa', must)
    check('查覆盖', miss == ['200 %'], str(miss))
    check('提示词块', checklist_block([]) == '' and '19 μm、46 μm' in checklist_block(must))
    bad = unverified_numbers('图3 显示 12.5 MPa，1000 次循环，2020 年，第 5 组，3 种方法，缺 88.8 MPa',
                             'strength 12.5 MPa, 1 000 cycles, 2020 paper, Figure 3')
    check('查来源', bad == ['88.8'], str(bad))
    print('\n%d/%d 通过' % (5 - len(_fail), 5))
    return 0 if not _fail else 1


if __name__ == '__main__':
    sys.exit(main())
