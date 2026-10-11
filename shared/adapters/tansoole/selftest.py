# -*- coding: utf-8 -*-
"""tansoole 自测：规格、货期、一行、汇总都用 2026-10-11 苯硼酸（98-80-6）实测页面上的写法离线验。
真去探索平台搜一次藏在 --live 后面（只在主力机、而且人已经登录过时有意义）。"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.adapters import tansoole
from shared.kernel.cli import flag


def main():
    ok = total = 0

    def check(name, cond, detail=''):
        nonlocal ok, total
        total += 1
        if cond:
            print(f'  [PASS] {name}'); ok += 1
        else:
            print(f'  [FAIL] {name}  {detail}')

    check('规格 5g / 100G / 10GR / 2.5kg → 克数', tansoole.parse_spec('5g') == {'qty': 5, 'unit': 'g', 'grams': 5}
          and tansoole.parse_spec('100G')['grams'] == 100 and tansoole.parse_spec('10GR')['unit'] == 'g'
          and tansoole.parse_spec('2.5kg')['grams'] == 2500)
    check('规格 500ML → 毫升、没有克数；「1支」认不出 → text', tansoole.parse_spec('500ML') == {'qty': 500, 'unit': 'mL'}
          and tansoole.parse_spec('1支') == {'text': '1支'} and tansoole.parse_spec('') == {})
    check('货期：现货', tansoole.parse_lead('现货') == {'in_stock': True, 'futures': False, 'lead_days': None})
    lt = tansoole.parse_lead('2-4个工作日 (以Sigma库存为准)')
    check('货期：几个工作日 + 括号备注', lt['lead_days'] == [2, 4] and lt['note'] == '以Sigma库存为准' and not lt['in_stock'], str(lt))
    check('货期：期货、「特价 现货」', tansoole.parse_lead('期货')['futures'] and tansoole.parse_lead('特价 现货')['in_stock'])
    check('货期：单个数「3个工作日」', tansoole.parse_lead('3个工作日')['lead_days'] == [3, 3])
    row = tansoole.norm_row({'product_no': '014115036', 'url': '/upload/detail/01/E1W4_YPL9_014115036.html', 'catalog_no': '92248K',
                             'brand': 'Adamas', 'spec': '500g', 'param': '99.5%(LC-MS)', 'grade': 'RG', 'special': True,
                             'lead': '现货', 'action': '购买', 'compound': '98-80-6'}, 4)
    check('一行 → 品牌 / 规格克数 / 纯度 / 等级 / 现货 / 特价 / 绝对网址',
          row['brand'] == 'Adamas' and row['grams'] == 500 and row['purity'] == '99.5%(LC-MS)' and row['grade'] == 'RG'
          and row['in_stock'] and row['on_sale'] and row['url'].startswith('https://www.tansoole.com/upload/') and row['rank'] == 4, str(row))
    check('一行里没有任何价格字段', not any('price' in k for k in row), str(list(row)))
    tci = tansoole.norm_row({'product_no': '016337895', 'brand': 'TCI', 'spec': '100G', 'param': '', 'grade': '',
                             'lead': '期货', 'action': '询价'})
    check('期货 + 询价、空纯度 → None', tci['futures'] and tci['action'] == '询价' and tci['purity'] is None and 'on_sale' not in tci, str(tci))
    acr = tansoole.norm_row({'brand': 'Acros', 'spec': '50GR', 'lead': '40-50个工作日', 'action': '购买'})
    sm = tansoole.summarize([row, tci, acr, dict(row, spec='5g', grams=5, purity='98%+(LC-MS)')])
    check('汇总：现货条数、期货、品牌按现货排、现货最大包装、最快非现货',
          sm['n_in_stock'] == 2 and sm['n_futures'] == 1 and list(sm['brands'])[0] == 'Adamas'
          and sm['brands']['Adamas']['max_stock_grams'] == 500 and sm['brands']['Adamas']['purities'] == ['99.5%(LC-MS)', '98%+(LC-MS)']
          and sm['fastest_non_stock_days'] == 50, str(sm))
    check('结果数「共 55 条」', tansoole.parse_count('上一页 1 2 下一页 共 55 条 50 条/页') == 55 and tansoole.parse_count('x') is None)
    check('登录与验证页判断', tansoole._logged_in('titan374200：欢迎来到探索网！[退出登录]') and not tansoole._logged_in('登录 注册')
          and tansoole._is_captcha('请完成安全验证') and not tansoole._is_captcha('产品编号 … 验证码登录'))
    check('抽取脚本不碰价格栏与「复制」按钮', 'row05' not in tansoole._ROWS_JS and 'copyText' not in tansoole._ROWS_JS
          and 'icon-listcopy' not in tansoole._ROWS_JS and 'onclick' not in tansoole._ROWS_JS)

    if flag('--live'):
        try:
            r = tansoole.search('98-80-6')
            check(f'真搜 98-80-6：{r["code"]} {r["count"]} 条，登录 {r["logged_in"]}', r['code'] == 'OK' and r['items'], r.get('why', ''))
        except Exception as e:
            check('真搜探索平台', False, f'{type(e).__name__}: {e}')
    else:
        print('  [SKIP] 真去探索平台搜（加 --live，只在主力机有意义）')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
