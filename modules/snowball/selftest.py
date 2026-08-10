# -*- coding: utf-8 -*-
"""snowball 自测：验证雪球扩展的核心承诺。

核心承诺是「能从一篇种子拿到它的参考文献与被引文献，且带完整元数据」。
OpenAlex 免费无密钥，所以这里做真实调用是安全的（不烧用户额度）。
用法: python modules/snowball/selftest.py
"""
import sys, os

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from modules.snowball import expand, work_by_doi, _abstract, _norm

# 用户库里真实存在的一篇 PBS 机理文章，方向对口，适合当测试种子
SEED = '10.1016/j.mtchem.2023.101677'


def main():
    ok = 0
    total = 6

    # 1. 摘要倒排索引还原 —— OpenAlex 的摘要是倒排的，不还原就没法用
    inv = {'Boron': [0], 'oxygen': [2], 'bonds': [3], 'are': [1]}
    if _abstract(inv) == 'Boron are oxygen bonds':
        print('  [PASS] 摘要倒排索引正确还原'); ok += 1
    else:
        print(f'  [FAIL] 还原结果异常: {_abstract(inv)!r}')

    if _abstract(None) == '' and _abstract({}) == '':
        print('  [PASS] 空摘要安全'); ok += 1
    else:
        print('  [FAIL] 空摘要处理异常')

    # 2. 字段归一：必须与 sciverse.search_papers 同构，才能共用 lib_match
    w = {'title': ' T ', 'doi': 'https://doi.org/10.1/x', 'publication_year': 2024,
         'cited_by_count': 7, 'id': 'https://openalex.org/W123',
         'primary_location': {'source': {'display_name': 'Nature'}, 'is_oa': True}}
    n = _norm(w)
    if (n['title'] == 'T' and n['doi'] == '10.1/x' and n['venue'] == 'Nature'
            and n['citations'] == 7 and n['openalex_id'] == 'W123'):
        print('  [PASS] 字段归一（与 sciverse 结构一致，可共用 lib_match）'); ok += 1
    else:
        print(f'  [FAIL] 归一结果异常: {n}')

    # 3. 查不到的 DOI 返回 None 而不是抛异常（批量时要能跳过）
    if work_by_doi('10.9999/definitely-not-exist-xyz') is None:
        print('  [PASS] 查不到的 DOI 安全返回 None'); ok += 1
    else:
        print('  [FAIL] 不存在的 DOI 未正确处理')

    # 4+5. **核心承诺**：真实种子能拿到前后向文献，且带标题
    try:
        r = expand([SEED], direction='both', limit_per_seed=15)
        items = r['items']
        back = [i for i in items if i.get('from') == 'backward']
        fwd = [i for i in items if i.get('from') == 'forward']
        if back and fwd:
            print(f'  [PASS] 前后向都拿到：后向 {len(back)} 条 / 前向 {len(fwd)} 条'); ok += 1
        else:
            print(f'  [FAIL] 前后向不完整：后向 {len(back)} / 前向 {len(fwd)}')

        titled = [i for i in items if i['title']]
        if len(titled) >= len(items) * 0.8:
            print(f'  [PASS] {len(titled)}/{len(items)} 条有标题'
                  f'（这正是不用 Sciverse 引用接口的原因）'); ok += 1
            for i in items[:3]:
                print(f'         [{i["year"]}] 被引{i["citations"]:<5} {i["title"][:52]}')
        else:
            print(f'  [FAIL] 只有 {len(titled)}/{len(items)} 条有标题')
    except Exception as e:
        print(f'  [FAIL] 雪球扩展失败: {str(e)[:120]}')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
