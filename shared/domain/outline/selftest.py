# -*- coding: utf-8 -*-
"""outline 自测：骨架、数字 / 表格扫描、性能名与单位。纯逻辑，全离线、毫秒级。"""
import sys
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass
from shared.domain import outline as O
from shared.domain.outline import props, scan


def main():
    ok = total = 0

    total += 1
    a = props.parse_property('tensile strength: 12 MPa')
    b = props.parse_property('Mn: 3.2×10^4 g/mol')
    c = props.parse_property('degradation: 225-300 °C')
    d = props.parse_property('stretchability: >20 times')
    if (a['value'] == 12 and a['unit'] == 'MPa' and b['value'] == 32000
            and c['value_max'] == 300 and d['cmp'] == '>'):
        print('  [PASS] 性能字符串拆成能比大小的数（含科学计数、区间、大于号）'); ok += 1
    else:
        print(f'  [FAIL] 性能解析不对：{a} {b} {c} {d}')

    total += 1
    if (props.normalize_property_name('Ultimate tensile stress') == 'tensile strength'
            and props.normalize_property_name('断裂伸长率') == 'elongation at break'
            and props.normalize_property_name('Healing efficiency') == 'self-healing efficiency'
            and props.normalize_property_name('some odd prop') == 'some odd prop'):
        print('  [PASS] 性能名字归一：别名归到正名，词表外的原样留着'); ok += 1
    else:
        print('  [FAIL] 性能名字归一不对')

    # ── 洗表格：下面每一条都是 2026-09-07 在 42 篇真实全文里实测到的脏 ──

    total += 1
    cases = {r'$M_{n}$': 'Mn', r'$\overline{M}_{n}$': 'Mn',
             r'$T_{c,onset}$': 'Tc,onset', r'$k_{hn} \times 10^{-3}$': 'khn × 10-3'}
    bad = {k: scan.clean_label(k) for k, v in cases.items() if scan.clean_label(k) != v}
    if not bad:
        print('  [PASS] 表头里的 LaTeX 洗成人话（实测 150/428 条名字带 LaTeX）'); ok += 1
    else:
        print(f'  [FAIL] LaTeX 没洗干净：{bad}')

    total += 1
    # 误差棒和比号长得像单位。挂上假单位比没有单位更坏 —— 它会被当真去比大小。
    if (scan._clean_unit('± 1.7') == '' and scan._clean_unit(':1') == ''
            and scan._clean_unit('MPa') == 'MPa'):
        print('  [PASS] 误差棒与比号不当单位（实测 37 条挂过假单位）'); ok += 1
    else:
        print('  [FAIL] 假单位没拦住')

    total += 1
    # 一格塞两代样品，硬拆就是灌假数；误差棒是同一个数的精度，要留。
    if (scan._cell_number('PD 1.68 1.28') is None
            and scan._cell_number('12.4 (±0.10)') == '12.4'
            and scan._cell_number('10–20') == '10–20'):
        print('  [PASS] 一格多值不猜；误差棒剥掉、区间留住'); ok += 1
    else:
        print(f'  [FAIL] 一格多值判错：{scan._cell_number("PD 1.68 1.28")!r} / '
              f'{scan._cell_number("12.4 (±0.10)")!r} / {scan._cell_number("10–20")!r}')

    total += 1
    # 「名字里有两个数」当判据会误伤条件（200/800 是温度区间，不是数据）
    if (scan._is_collapsed('CFRP Laminate 8.31 13.74')
            and not scan._is_collapsed('Weight loss (%) 200/800')
            and not scan._is_collapsed('Energy loss coefficient 1st cycle')):
        print('  [PASS] 塌陷行整列丢掉，但不误伤「条件里带数字」的表头'); ok += 1
    else:
        print('  [FAIL] 塌陷判据误伤了正常表头')

    total += 1
    # 转置表：第一列是性能、表头是样品。**必须先洗 LaTeX 再判**，否则认不出来。
    t_md = ('Table 1. Properties.\n\n<table><tr><td></td><td>PDMS1</td><td>PDMS2</td></tr>'
            '<tr><td>$d_w$ (μm)</td><td>0.39</td><td>0.52</td></tr>'
            '<tr><td>apparent $E_a$ (kJ/mol)</td><td>61</td><td>72</td></tr></table>')
    rows = scan.scan_tables(t_md)
    sids = sorted({r['sample_id'] for r in rows})
    if sids == ['PDMS1', 'PDMS2'] and len(rows) == 4:
        print('  [PASS] 转置表转回来了（洗过 LaTeX 才认得出第一列是性能名）'); ok += 1
    else:
        print(f'  [FAIL] 转置表没转回来：样品={sids} 条数={len(rows)}')

    total += 1
    # 投料量属于配方，不该进测量层去跟别人比大小
    c_md = ('Table 2. Formulations.\n\n<table><tr><td>Sample</td><td>PA6 (wt%)</td>'
            '<td>Tensile strength (MPa)</td></tr>'
            '<tr><td>PA6/PBS-1</td><td>80</td><td>52.3</td></tr></table>')
    rows = scan.scan_tables(c_md)
    kinds = {r['raw_name']: r['kind'] for r in rows}
    if (kinds.get('PA6') == 'composition'
            and kinds.get('Tensile strength') == 'measurement'):
        print('  [PASS] 投料量与性能分开（wt% 的组分是配方，不是性能）'); ok += 1
    else:
        print(f'  [FAIL] 投料量没分出来：{kinds}')

    total += 1
    # 出处是脚本从同一段文字里读到的，不可能是编的
    if rows and all(r['location'] == 'Table 2' and r['method'] == 'script' for r in rows):
        print('  [PASS] 表格里的每条都带出处与 method=script'); ok += 1
    else:
        print(f'  [FAIL] 出处丢了：{[(r["location"], r["method"]) for r in rows]}')

    # ── 单位要洗干净（2026-09-08 实测驱动）────────────────────────────
    # 库里真出现过这些「单位」：'% in the first cycle to '、'h of healing'、
    # 'mJ mm -1'。后两者最阴 —— `1484.9 mJ mm-1` 与 `1484.9 mJ mm -1`
    # 去重时对不上号，**同一个数被算成两条**。云端模型也这么写，
    # 所以这是我们解析太宽，不是谁笨。
    total += 1
    cases = [('puncture energy: 1484.9 mJ mm -1', 'mJ mm-1'),
             ('toughness: 2059 kJ m -2', 'kJ m-2'),
             ('residual strain: 110 % in the first cycle to 150%', '%'),
             ('healing time: 18 h of healing', 'h'),
             ('residual strain: 10 % %', '%'),
             ('tensile strength: 12 MPa', 'MPa'),
             ('modulus: 3.2 MPa at 25 C', 'MPa')]
    bad = [(t, props.parse_property(t)['unit']) for t, want in cases
           if props.parse_property(t)['unit'] != want]
    if not bad:
        print('  [PASS] 脏单位洗干净（指数空格、拖着的整句话、重复符号）'); ok += 1
    else:
        print(f'  [FAIL] 单位没洗干净：{bad}')

    total += 1
    if (props.parse_property('tensile strength: 12 MPa')['value'] == 12
            and props.tidy_unit('') == '' and props.tidy_unit('  ') == ''):
        print('  [PASS] 洗单位不影响数值，空单位仍是空'); ok += 1
    else:
        print('  [FAIL] 洗单位把别的弄坏了')

    # 地址跨版本稳住（2026-10-04）：快速层与 MineRU 认出的标题数不同，节号会错位，按标题 / 原句找回
    total += 2
    body = 'The storage modulus of the borosiloxane network rose sharply at high frequency. ' * 3
    text_v = '# T\n\n## 1 Introduction\n\nIntro text here.\n\n## 2.2 Mechanical Properties\n\n' + body + '\n\n## 3 Conclusion\n\nDone.\n'
    st_v = ('# T\n\n## ABSTRACT\n\nAbs.\n\n## 1\n\n## Introduction\n\nIntro text here.\n\n## 2.2 Mechanical Proper‐ties\n\n'
            + body.replace('borosiloxane', 'boro­siloxane') + '\n\n## 3 Conclusion\n\nDone.\n')
    ot, os_ = O.build_outline(text_v), O.build_outline(st_v)
    old = O.find_section(ot, '2.2 Mechanical Properties')
    new = O.find_section(os_, '2.2 Mechanical Properties')
    title_of = {s['id']: s['title'] for s in os_['sections']}
    if old and new and old != new and 'Mechanical' in title_of.get(new, ''):
        print(f'  [PASS] 按标题找回节：快速层 {old} → 升级后 {new}（横线写法不同也认）'); ok += 1
    else:
        print('  [FAIL] 按标题找不回节', old, new)
    got = O.locate(st_v, os_, 'storage modulus of the borosiloxane network rose sharply')
    if got and got.partition('.')[0] == new:
        print('  [PASS] 按一句原文找回现在的地址'); ok += 1
    else:
        print('  [FAIL] 按原文定位错了', got, new)

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
