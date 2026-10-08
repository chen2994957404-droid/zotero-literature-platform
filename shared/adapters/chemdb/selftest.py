# -*- coding: utf-8 -*-
"""chemdb 自测：网址换页、结果数、去样板、登录判断都用 2026-10-08 实测到的真页面样例离线验。
真去 SciFinder / Reaxys 搜一次藏在 --live 后面（只在主力机、而且人已经登录过时有意义）。"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.adapters import chemdb
from shared.kernel.cli import flag

SF_LIST = 'https://scifinder-n.cas.org/search/reference/6ac75f55e8a9c94fbcb6172b/1'
RX_LIST = ('https://www.reaxys.com/#/results/citations/0/RX012_6959454385329218377/UlgwMTI9QyNIMDAyPVMjSDAwMT1S'
           '/list/65486b8a-8da0-4653-a4e7-bd2099149169/1/desc/WEIGHT')


def main():
    ok = total = 0

    def check(name, cond, detail=''):
        nonlocal ok, total
        total += 1
        if cond:
            print(f'  [PASS] {name}'); ok += 1
        else:
            print(f'  [FAIL] {name}  {detail}')

    check('SciFinder 换页：末尾页码换掉',
          chemdb.page_url('scifinder', SF_LIST, 3).endswith('/6ac75f55e8a9c94fbcb6172b/3'))
    check('Reaxys 换页：list/<uuid>/ 后面那个页码换掉、其余不动',
          chemdb.page_url('reaxys', RX_LIST, 2) == RX_LIST.replace('/1/desc/', '/2/desc/'))
    check('不是结果页 → 换页给空',
          chemdb.page_url('scifinder', 'https://scifinder-n.cas.org/search/all/6ac75f45', 2) == ''
          and chemdb.page_url('reaxys', 'https://www.reaxys.com/#/search/quick/results', 2) == '')
    check('读页码', chemdb.page_no('scifinder', SF_LIST) == 1 and chemdb.page_no('reaxys', RX_LIST) == 1)
    check('登录页认得出',
          chemdb.is_login('scifinder', 'https://sso.cas.org/as/authorization.oauth2?client_id=scifinder-n')
          and chemdb.is_login('reaxys', 'https://www.reaxys.com/#/login')
          and not chemdb.is_login('scifinder', SF_LIST))
    check('SciFinder 结果数在正文「26 Results」',
          chemdb.count_of('scifinder', 'x Reference Search | CAS SciFinder', 'Select All Results\n26 Results\nSort:') == 26)
    check('Reaxys 结果数在标题',
          chemdb.count_of('reaxys', 'Search results | Reaxys - 1,054 Documents for "x"', '') == 1054)
    check('读不出结果数 → None', chemdb.count_of('scifinder', '', 'nothing here') is None)
    t = chemdb.clean_text('Skip to Page Footer\n\nTitle A\nTitle A\nFeedback\n  By: X  \nCopyright © 2026 ACS')
    check('去样板、去空行、连续重复只留一行', t == 'Title A\nBy: X', repr(t))
    for bad, fn in (('pubmed', chemdb.check_db), ('patents', chemdb.check_kind)):
        try:
            fn(bad)
            check(f'不认识的「{bad}」要报错', False)
        except ValueError:
            check(f'不认识的「{bad}」要报错', True)
    check('kind 默认 references', chemdb.check_kind('') == 'references' and chemdb.check_db(' SciFinder ') == 'scifinder')
    check('sort 只认三种', chemdb.check_sort('Cited') == 'cited' and chemdb.check_sort('') == '')

    # v0.5：解析成字段（样例都是 2026-10-08 页面上的原样）
    b = chemdb.parse_sf_bib('China, CN117777727 A 2024-03-29 | Language: Chinese, Database: CAplus')
    check('SciFinder 专利出处 → 号 / 局 / 日期', b['type'] == 'patent' and b['patent_no'] == 'CN117777727 A'
          and b['office'] == 'China' and b['year'] == 2024 and b['language'] == 'Chinese', str(b))
    b = chemdb.parse_sf_bib('World Intellectual Property Organization, WO2019084603 A1 2019-05-09 | Language: English')
    check('SciFinder WO 专利（A1）', b['patent_no'] == 'WO2019084603 A1', str(b))
    b = chemdb.parse_sf_bib('Smart Materials and Structures (2023), 32(7), 074004  | Language: English, Database: CAplus')
    check('SciFinder 期刊出处 → 刊名 / 年', b['type'] == 'journal' and b['source'] == 'Smart Materials and Structures'
          and b['year'] == 2023, str(b))
    b = chemdb.parse_sf_bib('Langmuir | Language: English, Database: CAplus and MEDLINE')
    check('SciFinder 在印文章（没年份）', b['source'] == 'Langmuir' and b['year'] is None, str(b))
    it = chemdb.norm_sf_item({'rank': 3, 'title': 'T', 'authors': 'Parisi, M.; Allen, T.; ', 'citing': 5,
                              'bib': 'China, CN117777727 A 2024-03-29 | Language: Chinese', 'assignee': 'X Inst.',
                              'status': 'Alive', 'snippet': ' abc '})
    check('SciFinder 一条 → 作者拆开、专利带状态', it['authors'] == ['Parisi, M.', 'Allen, T.'] and it['status'] == 'alive'
          and it['assignee'] == 'X Inst.' and it['snippet'] == 'abc' and it['citing'] == 5, str(it))
    rx = chemdb.norm_rx_item({'idx': '1', 'type': 'Article', 'title': 'Novel <hi>Shear</hi>-Thickening Gel',
                              'authors': ['Pan, Fei'], 'source': 'Journal of Applied Polymer Science, 2025, vol. 142',
                              'link': 'https://lls.reaxys.com/xflink?aulast=Pan&doi=10.1002%2Fapp.57659&issn=1097-4628',
                              'doi': None, 'pubdate': '1754064000000', 'cited': '43',
                              'index_terms': ['<hi>Polyborosiloxane</hi>', 'Gels']})
    check('Reaxys 文章 → 去 <hi>、DOI 从链接取、年份、被引', rx['title'] == 'Novel Shear-Thickening Gel'
          and rx['doi'] == '10.1002/app.57659' and rx['year'] == 2025 and rx['cited'] == 43
          and rx['index_terms'] == ['Polyborosiloxane', 'Gels'] and rx['type'] == 'journal', str(rx))
    rx = chemdb.norm_rx_item({'idx': '4-5', 'type': 'Patent', 'title': 'Polypropylene/ <hi>shear</hi> gel',
                              'link': 'https://lls.reaxys.com/xflink?pubno=CN109666219&pubdate=2019&kindcode=A',
                              'members': ['CN109666219 A', 'CN109666219 B'], 'assignee': 'WANHUA CHEMICAL GROUP',
                              'office': 'CN', 'source': ''})
    check('Reaxys 专利族「4-5」→ rank 4、family_ranks [4,5]、号', rx['rank'] == 4 and rx['family_ranks'] == [4, 5]
          and rx['patent_no'] == 'CN109666219' and rx['assignee'] == 'WANHUA CHEMICAL GROUP' and rx['source'] is None, str(rx))

    if flag('--live'):
        for db in chemdb.DBS:
            try:
                r = chemdb.search(db, 'polyborosiloxane self-healing', max_chars=500)
                check(f'真搜 {db}：{r["code"]} {r["count"]}', r['code'] in ('OK', 'LOGIN_REQUIRED'), r.get('why', ''))
            except Exception as e:
                check(f'真搜 {db}', False, f'{type(e).__name__}: {e}')
    else:
        print('  [SKIP] 真去 SciFinder / Reaxys 搜（加 --live，只在主力机有意义）')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
