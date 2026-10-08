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
