# -*- coding: utf-8 -*-
"""crossref 自测：字段映射用离线样例验，联网那条查不通就跳过（不算失败）。"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters import crossref

SAMPLE = {
    'title': ['Shear stiffening gels for intelligent protection'],
    'author': [{'given': 'X.', 'family': 'Wang'}, {'name': 'Consortium X'}],
    'container-title': ['Advanced Materials'],
    'published-print': {'date-parts': [[2021, 5]]},
    'issued': {'date-parts': [[2020]]},
    'volume': '33', 'issue': '2', 'page': '1-9',
    'DOI': '10.1002/adma.202100000', 'URL': 'https://doi.org/10.1002/adma.202100000',
    'abstract': '<jats:p>A gel that stiffens.</jats:p>',
}


def main():
    ok = total = 0

    total += 1
    it = crossref.to_zotero_item(SAMPLE, tags=['待处理'])
    if (it['itemType'] == 'journalArticle'
            and it['title'].startswith('Shear stiffening')
            and it['publicationTitle'] == 'Advanced Materials'
            and it['DOI'] == '10.1002/adma.202100000'):
        print('  [PASS] Crossref 字段 → Zotero 条目'); ok += 1
    else:
        print(f'  [FAIL] 字段映射不对：{it}')

    total += 1
    if it['date'] == '2021-5':
        print('  [PASS] 日期优先取 published-print（不是 issued）'); ok += 1
    else:
        print(f'  [FAIL] 日期取错了：{it["date"]}')

    total += 1
    if it['abstractNote'] == 'A gel that stiffens.' and '<jats:' not in it['abstractNote']:
        print('  [PASS] 摘要去掉 JATS 标签'); ok += 1
    else:
        print(f'  [FAIL] 摘要没洗干净：{it["abstractNote"]}')

    total += 1
    names = [c['lastName'] for c in it['creators']]
    if names == ['Wang', 'Consortium X']:
        print('  [PASS] 作者含机构名（只有 name 没有 family）也不丢'); ok += 1
    else:
        print(f'  [FAIL] 作者解析不对：{names}')

    total += 1
    if it['tags'] == [{'tag': '待处理'}] and crossref.to_zotero_item(SAMPLE)['tags'] == []:
        print('  [PASS] 不传标签就不打标签（精读要花钱，别顺手触发）'); ok += 1
    else:
        print('  [FAIL] 标签处理不对')

    total += 1
    try:
        crossref.work('')
        print('  [FAIL] 空 DOI 应该抛 DoiNotFound')
    except crossref.DoiNotFound:
        print('  [PASS] 空 DOI 抛 DoiNotFound（可重试与不可重试分开）'); ok += 1

    # 联网那条：通了就验真实返回，不通按 SKIP（本机没网不是功能坏了）
    try:
        m = crossref.work('10.1002/adma.201703549')
        total += 1
        if (m.get('title') or [''])[0]:
            print(f'  [PASS] 真实查询：{(m["title"] or [""])[0][:50]}'); ok += 1
        else:
            print('  [FAIL] 真实查询没拿到标题')
    except crossref.CrossrefError as e:
        print(f'  [SKIP] Crossref 连不上（{str(e)[:40]}），跳过联网那条')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
