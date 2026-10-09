# -*- coding: utf-8 -*-
"""polyinfo 自测：三种页面（结果列表 / 样品列表 / 样品详情）的解析、验证码与登录判断，
都用 2026-10-09 实测到的真页面文字离线验。真去 PoLyInfo 查一次藏在 --live 后面（只在主力机、人已登录时有意义）。"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.adapters import polyinfo
from shared.kernel.cli import flag

LIST = '\n'.join([
    'Matches: 104 polymers were found.',
    'Homopolymer: 1  Copolymer: 27  Polymer Blend: 76',
    '«', 'Previous', '1', ' All Property',
    '1. poly(methyl methacrylate)',
    'PID: P040048 CU formula: C5H8O2 1124samples',
    '\tMedian\tMode\tVariance\tHistogram\t',
    'THERMAL PROPERTY\t\t\t\t\t',
    'Glass transition temperature [C]\t108.0\t105.0\t1129\t\t(1124points)',
    '2. poly(methyl methacrylate)-graft-polystyrene',
    'COID: P900211 CU formula: C8H8/C4H6O2/C5H8O2/C2H4O 3samples',
    '\tMedian\tMode\tVariance\tHistogram\t',
    'Glass transition temperature [C]\t90.00\t68.00, 90.00, 103.0\t313.0\t\t(3points)',
    '3. poly(prop-1-ene)//poly(methyl methacrylate)',
    'BDID: BD000088 CU formula: C3H6//C5H8O2 3samples',
    'Density [g/cm3]\t0.9110\t0.9040, 0.9110, 0.9600\t0.0009310\t\t(3points)',
    'BACK',
])

SAMPLES = '\n'.join([
    'Sample List (poly[(methyl methacrylate)-ran-(3-{tris[(trimethylsilyl)oxy]silyl}propyl methacrylate)])',
    'Search condition:', 'PID=P905362', 'Number of data points: 5',
    'NO.\tSAMPLE ID\tMATERIAL TYPE\tADDITIVES\tPOLYMER TYPE\tPROPERTY',
    '1\t0012580-002-002-001\tNeat resin\t-\tCopolymer\t',
    'Glass transition temperature 101[C]',
    'Gas diffusion coefficient (D) 9.3e-8[cm2/s]',
    '',
    '5\t0012580-002-006-001\tNeat resin\t-\tCopolymer\t',
    'Glass transition temperature 27[C]',
    '«', 'Previous',
])

INFO = '\n'.join([
    'Sample Information', 'CU Chemical Structure', 'Information:',
    'Sample ID:\t0012580-002-002-001',
    'Polymer ID:\tP905362',
    'Name:\tpoly[(methyl methacrylate)-ran-(3-{tris[(trimethylsilyl)oxy]silyl}propyl methacrylate)]',
    'Polymer type:\tCopolymer',
    'Polymerization informations:\tReactant： 3-methacryloxypropyl tris(trimethylsiloxy)silane (MTTS);7.4;mol%,methyl methacrylate;92.6;mol%',
    'Mechanisms： radical',
    'Reference:\tInoue, Hiroshi; Matsukawa, Kimihiro,Journal of Macromolecular Science, Part A: Pure and Applied Chemistry,A29,6,415-440,1992',
    '10.1080/10101329208052172',
    'Component:',
    '\tComponent 1\tComponent 2',
    'CUID of Component\tCU040048\tCU342214',
    'CU formula\tC5H8O2\tC16H38O5Si4',
    'Composition:',
    'CUID of Component\tCU342214\tCU040048',
    'Compotision[mol%]\t7.4\t92.6',
    'Property:',
    'Glass transition temperatures',
    '\t\tGlass transition temperature\t101[C]',
    '\t\tMeasurement conditions\tHeating rate;10C/min&2nd run',
    '\t\tMeasurement methods\tDSC',
    'Related Information:',
    'Compn. vs. Various properties of PMTTS-co-PMMA',
    '\tCompn. in feed(MTTS/MMA)[mol%]\tCompn. of polymer(MTTS/MMA)[mol%]\tTg[C]',
    '\t0/100\t0/100\t120',
    '\t62.4/37.6\t63.8/36.2\t27',
    '\t100/0\t100/0\t-7',
    'Links',
    'Other polymers in this literature',
])


def main():
    ok = total = 0

    def check(name, cond, detail: object = ''):
        nonlocal ok, total
        total += 1
        if cond:
            print(f'  [PASS] {name}'); ok += 1
        else:
            print(f'  [FAIL] {name}  {detail}')

    r = polyinfo.parse_list(LIST)
    check('结果列表：总数与均聚 / 共聚 / 共混计数',
          (r['count'], r['n_homopolymer'], r['n_copolymer'], r['n_blend']) == (104, 1, 27, 76), r)
    check('结果列表：三条、编号类型 PID / COID / BDID 都认',
          [(i['id_type'], i['id']) for i in r['items']] == [('PID', 'P040048'), ('COID', 'P900211'), ('BDID', 'BD000088')],
          [(i['id_type'], i['id']) for i in r['items']])
    p = r['items'][0]['properties'][0]
    check('结果列表：性质中位数、单位、点数',
          (p['name'], p['unit'], p['median'], p['points'], r['items'][0]['n_samples']) ==
          ('Glass transition temperature', 'C', 108.0, 1124, 1124), p)
    check('结果列表：多个众数原样留字符串', r['items'][1]['properties'][0]['mode'] == '68.00, 90.00, 103.0')

    s = polyinfo.parse_samples(SAMPLES)
    check('样品列表：两个样品、编号对', [x['sample_id'] for x in s['samples']] ==
          ['0012580-002-002-001', '0012580-002-006-001'] and s['n_points'] == 5, s)
    check('样品列表：科学计数法的值', s['samples'][0]['properties'][1] ==
          {'name': 'Gas diffusion coefficient (D)', 'value': 9.3e-8, 'unit': 'cm2/s'}, s['samples'][0]['properties'])
    check('样品列表：「-」的添加剂记成空', s['samples'][0]['additives'] is None)

    d = polyinfo.parse_sample_info(INFO)
    check('样品详情：基本信息', d['info'].get('Polymer ID') == 'P905362' and d['info'].get('Polymer type') == 'Copolymer',
          d['info'])
    check('样品详情：聚合信息多行并在一起', 'Mechanisms' in d['info'].get('Polymerization informations', ''))
    check('样品详情：出处与 DOI', d['doi'] == '10.1080/10101329208052172' and d['reference'].startswith('Inoue'), d)
    check('样品详情：两个组分', [c.get('CU formula') for c in d['components']] == ['C5H8O2', 'C16H38O5Si4'],
          d['components'])
    check('样品详情：组成 mol%', d['composition'] == [{'cuid': 'CU342214', 'value': 7.4, 'unit': 'mol%'},
                                                    {'cuid': 'CU040048', 'value': 92.6, 'unit': 'mol%'}], d['composition'])
    pr = d['properties'][0] if d['properties'] else {}
    check('样品详情：性质值 + 测量条件挂在同一条上',
          (pr.get('name'), pr.get('value'), pr.get('unit'), pr.get('measurement_methods')) ==
          ('Glass transition temperature', 101.0, 'C', 'DSC'), d['properties'])
    t = d['related_tables'][0] if d['related_tables'] else {}
    check('样品详情：原文的组成–性质表（表头 + 行）',
          t.get('title', '').startswith('Compn. vs.') and len(t.get('header') or []) == 3 and t.get('rows', [])[-1] == ['100/0', '100/0', '-7'],
          t)

    check('验证码认得出', polyinfo.is_captcha('...\nType the characters see in the picture below.\n')
          and not polyinfo.is_captcha(LIST))
    check('登录页认得出（DICE 的 b2c 登录）',
          polyinfo.is_login('https://dicelogin.b2clogin.com/dicelogin.onmicrosoft.com/b2c_1a_dpf_signin/oauth2/v2.0/authorize')
          and not polyinfo.is_login('https://polymer.nims.go.jp/PoLyInfo/search'))
    check('页面类型', [polyinfo.page_kind('https://polymer.nims.go.jp/PoLyInfo/' + x) for x in
                       ('search', 'polymer-list', 'sample-list', 'sample-information')] ==
          ['search', 'polymer_list', 'sample_list', 'sample_info'])
    check('分子式拆成元素格', polyinfo.formula_counts('C16H38O5Si4') == [('C', '16'), ('H', '38'), ('O', '5'), ('Si', '4')])
    for bad, why in (('C2H6Zn', '不认的元素'), ('CHBNOFSiP', '超过 6 种元素')):
        try:
            polyinfo.formula_counts(bad)
            check(f'分子式：{why}要拒', False)
        except ValueError:
            check(f'分子式：{why}要拒', True)
    check('编号格式', polyinfo.check_id(' p905362 ') == 'P905362')
    try:
        polyinfo.check_id('905362')
        check('编号格式：不像编号要拒', False)
    except ValueError:
        check('编号格式：不像编号要拒', True)

    if flag('--live'):
        st = polyinfo.status()
        print('  [LIVE] status:', st)
        if st.get('tab_open') and not st.get('captcha') and not st.get('login_page'):
            r = polyinfo.search(name='poly(methyl methacrylate)', prop='Density')
            check('[LIVE] 查 PMMA 密度', r['code'] == 'OK' and r['items'], r.get('why'))
    else:
        print('  [SKIP] 真查 PoLyInfo（加 --live；只在主力机、人已登录时有意义）')

    print(f'\npolyinfo selftest: {ok}/{total} passed')
    return 0 if ok == total else 1


if __name__ == '__main__':
    sys.exit(main())
