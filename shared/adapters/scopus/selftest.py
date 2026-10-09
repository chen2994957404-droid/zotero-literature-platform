# -*- coding: utf-8 -*-
"""scopus 自测：检索式与网址、结果行、总数、登录 / 验证判断，用 2026-10-09 实测到的结果页离线验。真查一次藏在 --live 后面。"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.adapters import scopus
from shared.kernel.cli import flag

ROW = {'rank': '8', 'eid': '2-s2.0-85048761550',
       'title': 'A self-healing, adaptive and conductive polymer composite ink for 3D printing of gas sensors',
       'href': 'https://www.scopus.com/pages/publications/85048761550?origin=resultslist',
       'authors': ['Wu, T.', 'Gray, E.', 'Chen, B.'],
       'source': 'Journal of Materials Chemistry C, 6(23), 页 6200–6207', 'year': '2018', 'cited': '95',
       'cited_href': 'https://www.scopus.com/results/results.uri?s=ref%282-s2.0-85048761550%29',
       'type': 'Article\xa0 • \xa0开放获取'}


def main():
    ok = total = 0

    def check(name, cond, detail: object = ''):
        nonlocal ok, total
        total += 1
        if cond:
            print(f'  [PASS] {name}'); ok += 1
        else:
            print(f'  [FAIL] {name}  {detail}')

    check('普通词套 TITLE-ABS-KEY', scopus.build_query('polyborosiloxane') == 'TITLE-ABS-KEY(polyborosiloxane)')
    check('已是检索式就原样', scopus.build_query('TITLE-ABS-KEY(borosiloxane) AND PUBYEAR > 2019') ==
          'TITLE-ABS-KEY(borosiloxane) AND PUBYEAR > 2019' and scopus.build_query('DOI(10.1039/c4ra00001a)').startswith('DOI('))
    u = scopus.results_url('polyborosiloxane', 'cited')
    check('结果页网址：按被引排序、检索式编码', 'sort=cp-f' in u and u.endswith('s=TITLE-ABS-KEY%28polyborosiloxane%29'), u)
    try:
        scopus.results_url('x', 'newest')
        check('不认的排序要拒', False)
    except ValueError:
        check('不认的排序要拒', True)

    it = scopus.parse_rows([ROW])[0]
    check('结果行：序号 / EID / 标题 / 作者', (it['rank'], it['eid'], it['authors']) == (8, '2-s2.0-85048761550', ['Wu, T.', 'Gray, E.', 'Chen, B.'])
          and it['title'].startswith('A self-healing'), it)
    check('结果行：刊名与卷期页分开、年份、被引数', (it['source'], it['citation'], it['year'], it['cited']) ==
          ('Journal of Materials Chemistry C', '6(23), 页 6200–6207', 2018, 95), it)
    check('结果行：类型与开放获取、被引链接', it['type'] == 'Article' and it['open_access'] is True and 'ref%28' in it['cited_by_url'])
    check('总数（中文界面 / 英文界面）', scopus.parse_count('排序 183 篇文献 显示') == 183
          and scopus.parse_count('1,204 documents found') == 1204 and scopus.parse_count('无') is None)
    check('登录页 / 验证页认得出', scopus.is_login('https://id.elsevier.com/as/authorization.oauth2?x')
          and not scopus.is_login('https://www.scopus.com/results/results.uri?s=x')
          and scopus.is_captcha('Please verify you are human') and not scopus.is_captcha('183 篇文献'))

    if flag('--live'):
        st = scopus.status()
        print('  [LIVE] status:', st)
        if st.get('tab_open') and not st.get('login_page'):
            r = scopus.search('polyborosiloxane', 'cited')
            check('[LIVE] 查 polyborosiloxane', r['code'] == 'OK', r.get('why'))
    else:
        print('  [SKIP] 真查 Scopus（加 --live；只在主力机、人已登录时有意义）')

    print(f'\nscopus selftest: {ok}/{total} passed')
    return 0 if ok == total else 1


if __name__ == '__main__':
    sys.exit(main())
