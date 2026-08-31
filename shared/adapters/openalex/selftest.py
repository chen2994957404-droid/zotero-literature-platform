# -*- coding: utf-8 -*-
"""openalex 自测：字段归一对不对、摘要还原对不对、真调一次 API 通不通。
用法: python shared/adapters/openalex/selftest.py

前半段离线（用假的 work 记录），后半段真连 OpenAlex（免费无需密钥）。
**重点验字段名**：引用数必须叫 `citations` —— 重构前这里出过事，
paper_discovery 发 `cited_by`、discover 读 `cited`，两边对不上，
结果走 OpenAlex 检索时引用数永远是 0，还连累了按被引排序。
"""
import sys

from shared.adapters import openalex
from shared.kernel import errors

FAKE = {
    'id': 'https://openalex.org/W123',
    'doi': 'https://doi.org/10.1021/fake',
    'title': '  A fake work  ',
    'publication_year': 2019,
    'cited_by_count': 42,
    'primary_location': {'source': {'display_name': 'J. Fake Chem.'},
                         'is_oa': True, 'landing_page_url': 'https://x/y'},
    'open_access': {'is_oa': True},
    'abstract_inverted_index': {'Dynamic': [0], 'boron': [1], 'bonds': [2]},
    'authorships': [{'author': {'display_name': 'Qi Wu'}}],
}


def main():
    ok = total = 0

    # ── 离线部分 ──
    d = openalex.normalize(FAKE)

    total += 1
    if d['citations'] == 42:
        print('  [PASS] 引用数字段叫 citations（全平台统一）'); ok += 1
    else:
        print(f'  [FAIL] citations 不对: {d.get("citations")}')

    total += 1
    if d['doi'] == '10.1021/fake':
        print('  [PASS] DOI 去掉了 https://doi.org/ 前缀'); ok += 1
    else:
        print(f'  [FAIL] DOI 没归一: {d["doi"]}')

    total += 1
    checks = (d['title'] == 'A fake work' and d['year'] == 2019
              and d['venue'] == 'J. Fake Chem.' and d['is_oa'] is True
              and d['openalex_id'] == 'W123' and d['first_author'] == 'Qi Wu')
    if checks:
        print('  [PASS] 标题/年份/期刊/OA/id/一作 都归一正确'); ok += 1
    else:
        print(f'  [FAIL] 字段归一有问题: {d}')

    total += 1
    if d['abstract'] == 'Dynamic boron bonds':
        print('  [PASS] 倒排索引摘要还原正确'); ok += 1
    else:
        print(f'  [FAIL] 摘要还原不对: {d["abstract"]!r}')

    total += 1
    if openalex.restore_abstract(None) == '' and openalex.restore_abstract({}) == '':
        print('  [PASS] 没有摘要时返回空串而不是崩'); ok += 1
    else:
        print('  [FAIL] 空摘要处理不对')

    total += 1
    try:
        openalex.search('   ')
        print('  [FAIL] 空检索词竟然没报错')
    except errors.BadInputError:
        print('  [PASS] 空检索词被挡住'); ok += 1

    # ── 联网部分 ──
    total += 1
    try:
        items, count = openalex.search('polyborosiloxane', limit=3)
        if items and all(isinstance(it.get('citations'), int) for it in items):
            print(f'  [PASS] 真实检索通：共 {count} 篇，取回 {len(items)} 篇')
            print(f'         示例: [{items[0]["year"]}] {items[0]["title"][:52]}')
            ok += 1
        else:
            print(f'  [FAIL] 真实检索返回异常: {items[:1]}')
    except errors.PlatformError as e:
        print(f'  [SKIP] 连不上 OpenAlex（离线？）: {e}')
        total -= 1

    print(f'  {ok}/{total} 通过')
    return 0 if ok == total else 1


if __name__ == '__main__':
    sys.exit(main())
