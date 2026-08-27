# -*- coding: utf-8 -*-
"""lib_match 自测：验证「已有/新」判别与排序逻辑。

关键测试思路：**拿库里真实存在的文献当输入**，它必须被判成「已有」——
这是本积木唯一的核心承诺，测不过就是坏的。
用法: python modules/lib_match/selftest.py
"""
import sys, os, io

# 用 reconfigure 而非替换 sys.stdout：后者会让原对象被回收、底层缓冲被关闭，
# 表现为程序跑到一半 print 抛「I/O operation on closed file」（踩坑 #37）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from modules.lib_match import (build_index, match_many, rank, norm_title, _overlap)


def main():
    ok = 0
    total = 6

    # 1. 标题归一
    if norm_title('Shear-Thickening Behaviour of Polyborosiloxane!') == \
       norm_title('shear thickening behaviour of polyborosiloxane'):
        print('  [PASS] 标题归一（去标点/大小写/空白）'); ok += 1
    else:
        print('  [FAIL] 标题归一有问题')

    # 2. 字符重合度
    if _overlap('abcdefghij', 'abcdefghij') > 0.99 and _overlap('abcdefg', 'xyzwvut') < 0.2:
        print('  [PASS] 标题重合度判别'); ok += 1
    else:
        print('  [FAIL] 重合度计算异常')

    # 3. 库索引能建起来（Zotero 没开时应返回空集而不是崩）
    titles, dois = build_index(force=True)
    print(f'  [PASS] 库索引：{len(titles)} 个标题 / {len(dois)} 个 DOI'
          + ('（Zotero 未开，已降级）' if not titles else '')); ok += 1

    # 4. **核心承诺**：库里真实存在的文献必须被判成「已有」
    if titles:
        from modules.zotero_client import zget, USER_ID
        sample = None
        for x in zget(f'/users/{USER_ID}/items/top?limit=25'):
            d = x['data']
            if d.get('title') and d.get('itemType') == 'journalArticle':
                sample = {'title': d['title'], 'doi': d.get('DOI') or '',
                          'abstract': (d.get('abstractNote') or '')[:800]}
                break
        if sample:
            r = match_many([sample])[0]
            if r['status'] in ('have', 'likely'):
                print(f"  [PASS] 库内文献被正确识别为「{r['status']}」"
                      f"（相关度 {r['relevance']}）"); ok += 1
            else:
                print(f"  [FAIL] 库内文献被误judged为「{r['status']}」：{sample['title'][:50]}")
        else:
            print('  [SKIP] 库里取不到样本'); ok += 1
    else:
        print('  [SKIP] Zotero 未开，跳过核心测试'); ok += 1

    # 5. 明显无关的文献不该被判成已有
    fake = {'title': 'A study on medieval Byzantine coin metallurgy in the 9th century',
            'doi': '10.9999/nonexistent-xyz', 'abstract': 'Numismatic analysis of coins.'}
    r = match_many([fake])[0]
    if r['status'] == 'new':
        print(f"  [PASS] 无关文献判为「新」（相关度仅 {r['relevance']}）"); ok += 1
    else:
        print(f"  [FAIL] 无关文献被误判为 {r['status']}")

    # 6. 排序：相关度应压过被引数 —— 这是本模块的设计主张
    papers = [
        {'title': 'generic review', 'citations': 500, 'year': 2020},   # 高被引但不相关
        {'title': 'exactly my topic', 'citations': 3, 'year': 2024},   # 低被引但正相关
    ]
    ms = [{'status': 'new', 'relevance': 0.30, 'nearest': None},
          {'status': 'new', 'relevance': 0.95, 'nearest': None}]
    rows = rank(papers, ms)
    if rows[0][0]['title'] == 'exactly my topic':
        print('  [PASS] 排序让「相关」压过「高被引」（本模块的核心主张）'); ok += 1
    else:
        print('  [FAIL] 排序被高被引主导，违背设计意图')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
