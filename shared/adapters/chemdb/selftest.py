# -*- coding: utf-8 -*-
"""chemdb 自测：网址换页、结果数、去样板、登录判断都用 2026-10-08 实测到的真页面样例离线验。
真去 SciFinder / Reaxys 搜一次藏在 --live 后面（只在主力机、而且人已经登录过时有意义）。"""
import re
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

    # v0.6：CAS 号与结构式（样例都是 2026-10-08 页面上的原样）
    check('CAS 号：格式 + 校验位（98-80-6 对、98-80-5 错、日期不算）',
          chemdb.is_cas_rn('98-80-6') and chemdb.is_cas_rn('10043-35-3') and not chemdb.is_cas_rn('98-80-5')
          and not chemdb.is_cas_rn('2024-03-29') and not chemdb.is_cas_rn('OB(O)c1ccccc1'))
    check('match 只认三种、默认 exact', chemdb.check_match('') == 'exact' and chemdb.check_match('Substructure') == 'substructure')
    check('计数：51K / 1,194 / Documents - 60,242',
          chemdb.parse_count('Get51Kreferences') == 51000 and chemdb.parse_count('Get1,194references') == 1194
          and chemdb.parse_count('Documents - 60,242') == 60242 and chemdb.parse_count('Suppliers') is None)
    sub = chemdb.norm_sf_substance({'rank': 1, 'rn': '10043-35-3', 'name': '',
                                    'lines': ['10043-35-3', 'BH3O3', 'Boric acid (H3BO3)', '1'],
                                    'refs': 'Get133Kreferences', 'rxns': 'Get20Kreactions', 'sup': 'Get189Suppliers'})
    check('SciFinder 物质卡片 → CAS 号 / 分子式 / 名字 / 计数（K 标约数）',
          sub['cas_rn'] == '10043-35-3' and sub['formula'] == 'BH3O3' and sub['name'] == 'Boric acid (H3BO3)'
          and sub['n_references'] == 133000 and sub['n_suppliers'] == 189 and sub['counts_rounded'], str(sub))
    rs = chemdb.norm_rx_substance({'name': 'phenylboronic acid', 'lines': (
        '1|(OH)2B(C6H5)|Number of Suppliers: 141|phenylboronic acid|(OH)2B(C6H5)|Molecular Weight:|121.931|'
        'Reaxys Registry Number|970972|CAS Registry Number:|98-80-6|Preparations - 187|Reactions - 86,920|'
        'Documents - 60,242|Physical Data - 285|Spectra - 315|Bioactivity - 3,229').split('|')})
    check('Reaxys 物质条目 → CAS 号 / Reaxys 号 / 分子量 / 文献·反应·物性计数',
          rs['cas_rn'] == '98-80-6' and rs['reaxys_rn'] == '970972' and rs['mw'] == 121.931
          and rs['n_documents'] == 60242 and rs['n_reactions'] == 86920 and rs['n_physical_data'] == 285
          and rs['n_suppliers'] == 141 and rs['rank'] == 1, str(rs))

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
    rx2 = chemdb.norm_rx_item({'idx': '2', 'type': 'Article', 'title': '<hi><mark>Self-healing</mark></hi> PDMS',
                               'index_terms': ['<mark>A</mark>', 'A', 'B'], 'snippet': 'x' * 900,
                               'authors': ['a%d' % i for i in range(12)]})
    check('Reaxys 去 <mark>、索引词去重、片段与作者限长', rx2['title'] == 'Self-healing PDMS'
          and rx2['index_terms'] == ['A', 'B'] and len(rx2['snippet']) <= chemdb.MAX_SNIPPET + 1
          and len(rx2['authors']) == chemdb.MAX_AUTHORS and rx2['n_authors'] == 12, str(rx2)[:300])
    check('排序：SciFinder 的选项文字认得出',
          re.search(chemdb.SORTS['cited'], 'Times Cited', re.I) and re.search(chemdb.SORTS['date'], 'Publication Date: Newest', re.I)
          and not re.search(chemdb.SORTS['date'], 'Publication Date: Oldest', re.I) is None)
    # v0.7（Claude Science 0.6.2 测试报告）
    check('分面计数 13.4K / (247) → 整数，读不成数给 None（不出 NaN）',
          chemdb.facet_counts({'Concept': {'Self-healing materials': '247', 'Polymers': '13.4K', 'x': 'abc', 'y': None}})
          == {'Concept': {'Self-healing materials': 247, 'Polymers': 13400, 'x': None, 'y': None}})
    check('检索解读：网页提示语不算', chemdb.clean_qi('Try using Advanced Search to build boolean queries.') is None
          and chemdb.clean_qi('boron and siloxane') == 'boron and siloxane')
    su = chemdb.norm_sf_substance({'rn': 'Retrieve CAS RN', 'name': 'Select Substance 3',
                                   'lines': ['Retrieve CAS RN', 'C6H7BO2', 'Phenylboronic acid', 'Select Substance 3', '3']})
    check('界面字不进字段：CAS 号 / 名字', su['cas_rn'] is None and su['name'] == 'Phenylboronic acid'
          and su['formula'] == 'C6H7BO2', str(su))
    old = chemdb.norm_rx_item({'idx': '3', 'type': 'Article', 'title': 'No title', 'source': 'Zeitschrift fuer Kristallographie, 1888, vol. 13',
                               'onlinedate': '1199145600000'})
    check('Reaxys 老文献：年份信出处（1888，不是录入日 2008）、「No title」→ None',
          old['year'] == 1888 and old['title'] is None, str(old))
    pt = chemdb.norm_rx_item({'idx': '2', 'type': 'Patent', 'title': 'Process', 'assignee': 'UBE INDUSTRIES - EP436314, 1991, A1',
                              'link': 'https://lls.reaxys.com/xflink?pubno=EP436314&pubdate=1991&kindcode=A1'})
    check('Reaxys 专利申请人不带专利号', pt['assignee'] == 'UBE INDUSTRIES', str(pt))
    rs2 = chemdb.norm_rx_substance({'name': 'sodium borate', 'lines': ['2', 'BO3(3-)*3Na(1+)', 'CAS Registry Number:', 'Retrieve CAS RN',
                                                                        'Documents - 2,440']})
    check('Reaxys 物质没有 CAS 号 → None（不是「Retrieve CAS RN」）', rs2['cas_rn'] is None and rs2['n_documents'] == 2440, str(rs2))
    poly = chemdb.norm_sf_substance({'rn': '25265-77-4', 'lines': ['25265-77-4', '(C6H6B2O4)x', '2',
                                                                   'Boronic acid, B,B′-1,4-phenylenebis-, homopolymer']})
    check('高分子分子式 (C6H6B2O4)x，不是「2」', poly['formula'] == '(C6H6B2O4)x' and poly['name'].startswith('Boronic'), str(poly))
    check('分子式：水合物认、名字不认', bool(chemdb._FORMULA_RE.match('H3BO3·xH2O')) and not chemdb._FORMULA_RE.match('Boric acid'))
    mc = chemdb.norm_sf_substance({'rn': '2488884-13-3', 'formula': '(C6H6B2O4.C6H4Br2.C6H2Br4…',
                                   'name': 'Boronic acid, B,B′-1,4-phenylenebis-, polymer with 1,4-dibromobenzene and 1,2,4,…',
                                   'lines': ['2488884-13-3', 'Images of a multi component structure including C A S RNs: '
                                             '4612-26-4, 636-28-2, and 106-37-6.', '(C6H6B2O4.C6H4Br2.C6H2Br4…', 'Components: 3']})
    check('多组分：截断的分子式标出来、组分 CAS 号与组分数', mc['formula'] == '(C6H6B2O4.C6H4Br2.C6H2Br4'
          and mc['formula_truncated'] and mc['component_cas_rns'] == ['4612-26-4', '636-28-2', '106-37-6']
          and mc['n_components'] == 3, str(mc))
    hcl = chemdb.norm_sf_substance({'rn': '1822335-11-4', 'formula': '(C6H16N2O2.C6H8B2O4.2ClH)…', 'lines': [
        '1822335-11-4', 'Images of a multi component structure including C A S RNs: 80685-25-2 and 4612-26-4.',
        '(C6H16N2O2.C6H8B2O4.2ClH)…', 'Components: 3']})
    check('组分比列出的 CAS 号多 → components_unlisted（盐酸没列号）', hcl['component_cas_rns'] == ['80685-25-2', '4612-26-4']
          and hcl.get('components_unlisted') == 1 and hcl['name'] is None, str(hcl))
    fr = chemdb.norm_sf_substance({'rn': '1144113-62-1', 'formula': 'C9H7NO.1/4C6H8B2O4', 'name': '',
                                   'lines': ['1144113-62-1', 'Images of a multi component structure including C A S RNs: '
                                             '4612-26-4 and 1532-72-5.', 'C9H7NO.1/4C6H8B2O4', 'Components: 2',
                                             'Boronic acid, B,B′-1,4-phenylenebis-, compd. with isoquinoline 2-oxide (1:1)']})
    check('分数配比的分子式照原样、名字跳过「Images of…」那行', fr['formula'] == 'C9H7NO.1/4C6H8B2O4'
          and fr['name'].startswith('Boronic acid') and 'formula_truncated' not in fr, str(fr))
    check('Reaxys 专利族「4-5」→ rank 4、family_ranks [4,5]、号', rx['rank'] == 4 and rx['family_ranks'] == [4, 5]
          and rx['patent_no'] == 'CN109666219' and rx['assignee'] == 'WANHUA CHEMICAL GROUP' and rx['source'] is None, str(rx))

    # 供应商（2026-10-11 苯硼酸 98-80-6 实测页面上的三种行）
    check('规格价：5 g, USD 10.00 → 每克 2 美元', chemdb.parse_qty_price('5 g, USD 10.00')
          == {'qty': 5, 'unit': 'g', 'currency': 'USD', 'price': 10.0, 'per_g': 2.0})
    pm = chemdb.parse_qty_price('500 mg, USD 19.00')
    check('毫克换算成每克、只有规格没价 → price None', pm['per_g'] == 38.0
          and chemdb.parse_qty_price('500 g')['price'] is None and 'per_g' not in chemdb.parse_qty_price('500 g'), str(pm))
    check('日元没有小数、千分位', chemdb.parse_qty_price('1,000 g, JPY 64200')['per_g'] == 64.2)
    sol = chemdb.parse_qty_price('10mM/1mL, USD 35.00')
    check('溶液写法认不出 → 原样 text，价格照取', sol.get('text') == '10mM/1mL, USD 35.00' and sol['price'] == 35.0, str(sol))
    cs = chemdb.parse_qty_price('5 g, Contact supplier')
    check('「Contact supplier」→ 规格照取、标询价', cs['qty'] == 5 and cs['price'] is None and cs['price_on_request'], str(cs))
    ext = ('/navigate/?answersPerPage=1&externalLink=https%253A%252F%252Fwww.chemscene.com%252F98-80-6.html&linkType=808')
    sup = chemdb.norm_sf_supplier({'supplier': 'AbaChemScene-US Stock', 'rn': '98-80-6', 'name': 'Phenylboronic acid',
                                   'purity': '95-98%', 'prices': ['5 g, USD 10.00', '500 g, USD 81.00'], 'more_prices': True,
                                   'tags': ['Bulk', 'Screening'], 'stock': 'Maintained in stock', 'ships': 'Ships within 1 week',
                                   'country': 'United States', 'order_no': 'Order Number: CS-W001090', 'order_href': ext}, 1)
    check('供应商一行 → 名字 / 纯度 / 价格 / 发货 / 国家 / 货号 / 真网址（两层编码解开）',
          sup['supplier'] == 'AbaChemScene-US Stock' and sup['ships_within'] == '1 week' and sup['order_number'] == 'CS-W001090'
          and sup['url'] == 'https://www.chemscene.com/98-80-6.html' and sup['orderable'] and sup['offers'] == ['Bulk', 'Screening']
          and sup['prices'][1]['per_g'] == 0.162 and sup['more_prices'], str(sup))
    wako = chemdb.norm_sf_supplier({'supplier': 'FUJIFILM Wako', 'purity': '', 'prices': ['500 g'], 'stock': '',
                                    'country': 'Japan', 'order_no': 'Order Number: 512-24095',
                                    'info_href': '/navigate/?externalLink=https%253A%252F%252Flabchem-wako.fujifilm.com%252Fx.html'})
    check('只有「Product Information」的行：不可直接下单、纯度空 → None', not wako['orderable'] and wako['purity'] is None
          and wako['url'] == 'https://labchem-wako.fujifilm.com/x.html' and 'offers' not in wako, str(wako))
    sm = chemdb.supplier_summary([sup, wako, dict(sup, supplier='BLD-China', country='China',
                                                  prices=[chemdb.parse_qty_price('100 g, CNY 50.00')])])
    check('汇总：家数、国家、各币种最便宜每克价', sm['n_suppliers'] == 3 and sm['countries']['United States'] == 1
          and sm['cheapest_per_g']['USD']['per_g'] == 0.162 and sm['cheapest_per_g']['CNY']['supplier'] == 'BLD-China'
          and sm['n_in_stock'] == 2, str(sm))
    check('供应商页能翻页', chemdb.page_url('scifinder', 'https://scifinder-n.cas.org/search/catalogItem/6acbb098/1', 2)
          .endswith('/catalogItem/6acbb098/2'))
    try:
        chemdb.search('reaxys', '98-80-6', kind='suppliers')
        check('Reaxys 不收 kind=suppliers', False)
    except ValueError:
        check('Reaxys 不收 kind=suppliers', True)

    # Reaxys 的 AI 检索会把关键词里的化学名换成结构式（2026-10-12 实测：BAPMA 的名字 + 主题词 → 「Structure as drawn」49310 篇）
    pv = [{'index': 0, 'count': 49310, 'kind': 'documents',
           'interpretation': 'Structure: Structure as drawn Titles, Abstracts, Keywords:"x"'},
          {'index': 1, 'count': 581, 'kind': 'substances', 'interpretation': 'Structure: Structure as drawn'}]
    pick, warn = chemdb.rx_pick_preview(pv, 'documents')
    check('非结构检索：解读里冒出 Structure 要警告', bool(pick and warn) and (pick or {}).get('index') == 0
          and str(warn).startswith('structure_injected'), str(warn))
    pick, warn = chemdb.rx_pick_preview(pv + [{'index': 2, 'count': 3, 'kind': 'documents',
                                               'interpretation': 'Titles, Abstracts, Keywords:"x"'}], 'documents')
    check('有不带结构的同类组就挑它', bool(pick and warn) and (pick or {}).get('index') == 2
          and str(warn).startswith('structure_group_skipped'), str(warn))
    check('结构检索本来就带 Structure，不警告', chemdb.rx_pick_preview(pv, 'documents', structure_search=True) == (pv[0], None))
    check('预览里没有这一类 → None', chemdb.rx_pick_preview(pv, 'reactions') == (None, None))
    # 物质详情页的物性表（2026-10-12 实测 BAPMA 的 Physical Data - 41）
    check('分组标签拆成名字和条数', chemdb.rx_fact_label('Boiling Point\xa0- 6') == ('Boiling Point', 6)
          and chemdb.rx_fact_label('Physical Data - 1,041') == ('Physical Data', 1041)
          and chemdb.rx_fact_label('Load More') == ('Load More', None))
    ref = chemdb.norm_rx_ref({'text': 'Edwards\n; Prakash\nJournal of Medicinal Chemistry, 1990\nFull Text\nCited 75 times\n'
                                      '(opens in a new window)\nDetails\nAbstract',
                              'doc_link': 'https://lls.reaxys.com/xflink?aulast=Edwards&title=J&doi=10.1021%2Fjm00167a014&issn=0022-2623',
                              'name': 'Article:Journal of Medicinal Chemistry, 1990, vol. 33, # 5, p. 1369 - 1375',
                              'authors': ['Edwards', 'Prakash']})
    check('出处：DOI 从 OpenURL 里取、类型与被引数', ref == {
        'citation': 'Journal of Medicinal Chemistry, 1990, vol. 33, # 5, p. 1369 - 1375', 'type': 'article',
        'authors': ['Edwards', 'Prakash'], 'doi': '10.1021/jm00167a014', 'cited': 75}, str(ref))
    pat = chemdb.norm_rx_ref({'text': 'Current Patent Assignee: Toho Rayon Co. - JP2135363, 1958\nChem.Abstr., 1964, vol. 60, '
                                      '# 2756f\nFull Text\nDetails'})
    check('没有链接的老专利退回文字、界面字去掉', pat['citation'] == 'Current Patent Assignee: Toho Rayon Co. - JP2135363, '
          '1958 Chem.Abstr., 1964, vol. 60, # 2756f' and pat['doi'] is None, str(pat))
    try:
        chemdb.substance_facts('105-83-9', section='spectra')
        check('section 只收 physical / other', False)
    except ValueError:
        check('section 只收 physical / other', True)

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
