# -*- coding: utf-8 -*-
"""discover 自测：验「已有/新」判别、排序主张、混合检索编排。

核心承诺只有两条，测的就是它们：
  ① 库里真实存在的文献必须被判成「已有」（不重复导入）
  ② 排序让「与我的方向相关」压过「被引数」（这是本工具的设计主张）
联网/Zotero/Ollama 不可用时相关的条目按 SKIP 处理 —— 那是环境问题，不是功能坏了。
"""
import sys

# 用 reconfigure 而非替换 sys.stdout：后者会让原对象被回收、底层缓冲被关闭，
# 表现为程序跑到一半 print 抛「I/O operation on closed file」（踩坑 #37）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from tools import discover
from tools.discover.match import (_overlap, build_index, match_many, norm_title, rank)


def main():
    ok = total = 0

    total += 1
    if norm_title('Shear-Thickening Behaviour of Polyborosiloxane!') == \
       norm_title('shear thickening behaviour of polyborosiloxane'):
        print('  [PASS] 标题归一（去标点/大小写/空白）'); ok += 1
    else:
        print('  [FAIL] 标题归一有问题')

    total += 1
    if _overlap('abcdefghij', 'abcdefghij') > 0.99 and _overlap('abcdefg', 'xyzwvut') < 0.2:
        print('  [PASS] 标题重合度判别'); ok += 1
    else:
        print('  [FAIL] 重合度计算异常')

    # 排序：相关度应压过被引数 —— 本工具的核心设计主张
    total += 1
    papers = [{'title': 'generic review', 'citations': 500, 'year': 2020},
              {'title': 'exactly my topic', 'citations': 3, 'year': 2024}]
    ms = [{'status': 'new', 'relevance': 0.30, 'nearest': None},
          {'status': 'new', 'relevance': 0.95, 'nearest': None}]
    if rank(papers, ms)[0][0]['title'] == 'exactly my topic':
        print('  [PASS] 排序让「相关」压过「高被引」（核心主张）'); ok += 1
    else:
        print('  [FAIL] 排序被高被引主导，违背设计意图')

    total += 1
    rows = rank(papers, [{'status': 'have', 'relevance': 0.95, 'nearest': None},
                         {'status': 'new', 'relevance': 0.30, 'nearest': None}])
    if rows[0][0]['title'] == 'exactly my topic':
        print('  [PASS] 库里已有的沉底（你已经有了）'); ok += 1
    else:
        print('  [FAIL] 已有的没沉底')

    # 多式合并去重：同一篇 DOI 只算一次，且统计每式的新增贡献
    total += 1
    real_fetch = discover.fetch_one
    discover.fetch_one = lambda q, limit, yf, oa, pref: (
        [{'title': 'A', 'doi': '10.1/a'}, {'title': 'B', 'doi': '10.1/b'}] if q == 'q1'
        else [{'title': 'B', 'doi': '10.1/B'}, {'title': 'C', 'doi': ''}], 99, 'fake')
    try:
        merged, total_hint, source, contrib, seen = discover.fetch_multi(
            ['q1', 'q2'], 10, None, True, 'relevance')
        if (len(merged) == 3 and contrib[0][2] == 2 and contrib[1][2] == 1
                and total_hint == 99):
            print('  [PASS] 多式合并去重 + 各式新增贡献（判断搜得够不够）'); ok += 1
        else:
            print(f'  [FAIL] 合并去重不对：{len(merged)} 篇 {contrib}')
    finally:
        discover.fetch_one = real_fetch

    total += 1
    if discover._key({'doi': '10.1/A'}) == discover._key({'doi': '10.1/a'}) \
            and discover._key({'title': 'Same Title!'}) == discover._key({'title': 'same title'}):
        print('  [PASS] 去重键：DOI 不分大小写，没 DOI 退回归一标题'); ok += 1
    else:
        print('  [FAIL] 去重键不对')

    # 下面几条要 Zotero / Ollama，环境不具备就 SKIP（不是功能坏了）
    titles, dois = build_index(force=True)
    print(f'  [INFO] 库索引：{len(titles)} 个标题 / {len(dois)} 个 DOI'
          + ('（Zotero 未开，已降级）' if not titles else ''))
    if titles:
        from shared.adapters.zotero_client import USER_ID, zget
        sample = None
        for x in zget(f'/users/{USER_ID}/items/top?limit=25'):
            d = x['data']
            if d.get('title') and d.get('itemType') == 'journalArticle':
                sample = {'title': d['title'], 'doi': d.get('DOI') or '',
                          'abstract': (d.get('abstractNote') or '')[:800]}
                break
        if sample:
            total += 1
            r = match_many([sample])[0]
            if r['status'] in ('have', 'likely'):
                print(f"  [PASS] 库内文献被正确识别为「{r['status']}」"
                      f"（相关度 {r['relevance']}）"); ok += 1
            else:
                print(f"  [FAIL] 库内文献被误判为「{r['status']}」：{sample['title'][:50]}")

        total += 1
        fake = {'title': 'A study on medieval Byzantine coin metallurgy in the 9th century',
                'doi': '10.9999/nonexistent-xyz', 'abstract': 'Numismatic analysis of coins.'}
        if match_many([fake])[0]['status'] == 'new':
            print('  [PASS] 无关文献判为「新」'); ok += 1
        else:
            print('  [FAIL] 无关文献被误判为已有')
    else:
        print('  [SKIP] Zotero 未开，跳过「已有/新」判别（要真实库才有意义）')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
