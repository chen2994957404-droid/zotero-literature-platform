# -*- coding: utf-8 -*-
"""ccdc 自测：拼检索网址、结果行、详情面板、验证页判断，用 2026-10-09 实测到的页面离线验。真查一次藏在 --live 后面。"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.adapters import ccdc
from shared.kernel.cli import flag

ROW = {'refcode': 'FUQVAS', 'dep': '2044318', 'icsd': '', 'text': '\n'.join([
    "Select this structure to include it when clicking 'Download Selected' or 'View Selected' Buttons",
    'FUQVAS', 'Deposition Number(s): 2044318', 'Space Group: P 1 (2)',
    'Cell: a 4.9858(7)Å b 7.2976(9)Å c 11.5769(13)Å, α 86.779(9)° β 87.374(10)° γ 85.973(10)°',
    'Compound Name: [2-(trifluoromethoxy)phenyl]boronic acid', 'Synonyms: 2-(trifluorometoxy)-phenylboronic acid'])}

DETAIL = '\n'.join([
    'FUWHIP : (3-(((4-Nitrophenyl)carbamoyl)amino)phenyl)boronic acid dimethyl sulfoxide solvate',
    'Space Group: P 21/c (14), Cell: a 13.6530(6)Å b 12.8836(6)Å c 19.9652(10)Å, α 90° β 105.7500(10)° γ 90°',
    '3D viewer', 'Additional details',
    'Deposition Number\t740807',
    'Data Citation\tM.Regueiro-Figueroa, K.Djanashvili CCDC 740807: Experimental Crystal Structure Determination, 2011, DOI: 10.5517/ccsvw0h',
    'Synonyms\t3-(3-(4-Nitrophenyl)ureido)phenylboronic acid dimethyl sulfoxide solvate',
    'Additional Deposition Numbers\t740810',
    'Deposited on\t04/02/2011',
    'Associated publications',
    'M.Regueiro-Figueroa, K.Djanashvili, European Journal of Organic Chemistry, 2010, 2010, 3237, DOI: 10.1002/ejoc.201000186',
    'Additional curated data',
    'More curated data including additional chemical ...',
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

    u = ccdc.search_url(compound='phenylboronic acid')
    check('拼检索网址（空格编码、默认全部已发表）',
          u == 'https://www.ccdc.cam.ac.uk/structures/Search?Compound=phenylboronic%20acid&DatabaseToSearch=Published', u)
    check('拼检索网址：多个条件', 'Ccdcid=740807' in ccdc.search_url(ident='740807', author='Allen')
          and 'Author=Allen' in ccdc.search_url(ident='740807', author='Allen'))
    for kw, why in (({}, '什么都不给'), ({'compound': 'x', 'database': 'COD'}, '不认的库')):
        try:
            ccdc.search_url(**kw)
            check(f'拼检索网址：{why}要拒', False)
        except ValueError:
            check(f'拼检索网址：{why}要拒', True)

    r = ccdc.parse_results([ROW])[0]
    check('结果行：结构代码 / CCDC 号 / 空间群 / 化合物名',
          (r['rank'], r['refcode'], r['deposition'], r['space_group'], r['name']) ==
          (1, 'FUQVAS', '2044318', 'P 1 (2)', '[2-(trifluoromethoxy)phenyl]boronic acid'), r)
    check('结果行：晶胞原样留着', r['cell'].startswith('a 4.9858(7)Å') and r['icsd'] is None)

    d = ccdc.parse_detail(DETAIL)
    check('详情：结构代码与名字', d.get('refcode') == 'FUWHIP' and d.get('name', '').startswith('(3-('), d)
    check('详情：空间群与晶胞', d.get('space_group') == 'P 21/c (14)' and d.get('cell', '').startswith('a 13.6530'), d)
    check('详情：CCDC 号、数据 DOI、沉积日期', (d.get('deposition'), d.get('data_doi'), d.get('deposited_on')) ==
          ('740807', '10.5517/ccsvw0h', '04/02/2011'), d)
    check('详情：关联论文与它的 DOI', d.get('publications') == [{'citation': DETAIL.splitlines()[10], 'doi': '10.1002/ejoc.201000186'}],
          d.get('publications'))

    check('验证页认得出', ccdc.is_captcha('Validation request - The Cambridge Crystallographic Data Centre (CCDC)', '')
          and ccdc.is_captcha('', 'please confirm you are not a robot') and not ccdc.is_captcha('Search - Access Structures', 'FUWHIP'))

    if flag('--live'):
        st = ccdc.status()
        print('  [LIVE] status:', st)
        if not st.get('captcha'):
            r = ccdc.search(compound='phenylboronic acid')
            check('[LIVE] 查苯硼酸', r['code'] in ('OK', 'NO_RESULTS'), r.get('why'))
    else:
        print('  [SKIP] 真查 CCDC（加 --live；只在主力机上有意义）')

    print(f'\nccdc selftest: {ok}/{total} passed')
    return 0 if ok == total else 1


if __name__ == '__main__':
    sys.exit(main())
