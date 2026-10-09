# -*- coding: utf-8 -*-
"""jcr 自测：期刊页解析（JIF、不含自引、JCI、开放获取、学科排名与分区）、下拉建议怎么挑、登录页判断，
用 2026-10-09 实测的 Macromolecules 期刊页离线验。真查一次藏在 --live 后面。"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.adapters import jcr
from shared.kernel.cli import flag

PROFILE = '\n'.join([
    'Journal profile', 'JCR Year', '2025', 'favorite_border', 'Favorite', 'file_download', 'Export',
    'MACROMOLECULES', '', 'ISSN', '', '0024-9297', '', 'EISSN', '', '1520-5835', '', 'JCR ABBREVIATION', '', 'MACROMOLECULES',
    '', 'Journal information', '', 'EDITION', '', 'Science Citation Index Expanded (SCIE)', '', 'CATEGORY', '', 'POLYMER SCIENCE',
    '', 'PUBLISHER', '', 'AMER CHEMICAL SOC', '',
    '2025 JOURNAL IMPACT FACTOR', '', '5.7', '', 'View calculation', '',
    'JOURNAL IMPACT FACTOR WITHOUT SELF CITATIONS', '', '4.9', '',
    'Journal Citation Indicator (JCI)', '', '1.11', '',
    '% OF CITABLE OA', '', '17.76%', '',
    'Rank by Journal Impact Factor', '', 'Journals within a category are sorted ...', '',
    'CATEGORY', 'POLYMER SCIENCE', '19/96', 'JCR YEAR\tJIF RANK\tJIF QUARTILE\tJIF PERCENTILE',
    '2025\t19/96\tQ1\t', '80.7', '', '2024\t15/94\tQ1\t', '84.6', '', '',
    'Rank by JIF before 2023 for POLYMER SCIENCE', 'EDITION', 'Science Citation Index Expanded (SCIE)',
    'JCR YEAR\tJIF RANK\tJIF QUARTILE\tJIF PERCENTILE', '2022\t11/86\tQ1\t', '87.8',
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

    p = jcr.parse_profile(PROFILE)
    check('期刊页：刊名 / ISSN / 出版商 / 版', (p['title'], p['issn'], p['eissn'], p['publisher'], p['edition']) ==
          ('MACROMOLECULES', '0024-9297', '1520-5835', 'AMER CHEMICAL SOC', 'Science Citation Index Expanded (SCIE)'), p)
    check('期刊页：年份、JIF、不含自引、JCI、开放获取比例',
          (p['year'], p['jif'], p['jif_no_self'], p['jci'], p['oa_pct']) == (2025, 5.7, 4.9, 1.11, 17.76), p)
    check('期刊页：学科排名只取最近一年、不混进 2023 年前的分版排名',
          p['ranks'] == [{'category': 'POLYMER SCIENCE', 'year': 2025, 'rank': '19/96', 'quartile': 'Q1', 'percentile': 80.7}], p['ranks'])
    check('期刊页：学科列表', p['categories'] == ['POLYMER SCIENCE'])

    sugg = [{'title': 'MACROMOLECULES', 'issns': ['0024-9297', '1520-5835']},
            {'title': 'BIOMACROMOLECULES', 'issns': ['1525-7797', '1526-4602']}]
    check('下拉：同名优先', jcr.pick_suggestion('Macromolecules', sugg) == 0)
    check('下拉：ISSN 对得上优先', jcr.pick_suggestion('1525-7797', sugg) == 1)
    check('下拉：没同名取第一个、没建议给 None', jcr.pick_suggestion('Macromol', sugg) == 0 and jcr.pick_suggestion('x', []) is None)
    check('登录页认得出', jcr.is_login('https://access.clarivate.com/login?app=jcr&detectSession=true')
          and not jcr.is_login('https://jcr.clarivate.com/jcr/home'))

    if flag('--live'):
        st = jcr.status()
        print('  [LIVE] status:', st)
        if st.get('tab_open') and not st.get('login_page'):
            r = jcr.journal('MACROMOLECULES')
            check('[LIVE] 查 Macromolecules', r['code'] == 'OK', r.get('why'))
    else:
        print('  [SKIP] 真查 JCR（加 --live；只在主力机、人已登录时有意义）')

    print(f'\njcr selftest: {ok}/{total} passed')
    return 0 if ok == total else 1


if __name__ == '__main__':
    sys.exit(main())
