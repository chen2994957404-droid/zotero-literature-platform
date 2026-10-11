# -*- coding: utf-8 -*-
"""查库的命令行入口（只解析参数，一行业务逻辑都没有）。

用法:
    python -m tools.library 库                          # 证据库有多大（全集；Zotero 只是子集）
    python -m tools.library 库 硼                        # 按标题/DOI/期刊搜证据库（不联网）
    python -m tools.library 库 10.1021/acs.macromol.5b00210
    python -m tools.library 找 "boronic ester hydrogen bond competition"   # 库内向量检索（零成本）
    python -m tools.library 找 "配比" --si                # 只搜补充材料
    python -m tools.library 引文 ABCD1234                 # 参考文献，标出库里已有的
    python -m tools.library 检索 10.1021/jacs.3c13392              # DOI 直接定位
    python -m tools.library 检索 "ionic skin"                       # 标题 / 作者 / 期刊里的词（每个词都要命中）
    python -m tools.library 检索 --通讯 武培怡 --年 2024-2026        # 通讯作者（中文名走团队名单，拼音不管顺序）
    python -m tools.library 检索 boronic --摘要 --有 精读             # 连摘要一起搜；只要已精读的
    python -m tools.library 检索 --团队 龚兴龙 --刊 "Adv"            # 某团队（含合作）、期刊名里带 Adv
    python -m tools.library 检索 --建索引                            # 从 OpenAlex 取作者 + 摘要（免费额度约 25 次）
    python -m tools.library 团队                         # 研究团队名单 + 每组挂了几篇（读缓存，不联网）
    python -m tools.library 团队 武培怡                   # 一个组：大导 / 小导 / 已独立 + 本组与合作文章
    python -m tools.library 团队 --重建                   # 重新取作者、挂组（OpenAlex 免费额度约 25 次）
    python -m tools.library stats                       # Zotero 统计 + 通不通
    python -m tools.library 盘点 [--明细]                # 库里有什么：类型 / 正文 / SI 三态 / 精读，两边对上
    python -m tools.library search 聚硼硅氧烷 --limit 10  # 搜标题作者年份
    python -m tools.library search 硼 --all              # --all = 连全文一起搜
    python -m tools.library search --tag 待处理          # 按标签
    python -m tools.library item ABCD1234                # 单篇完整信息
    python -m tools.library pdf ABCD1234                 # 正文 PDF 在哪
    python -m tools.library fulltext ABCD1234 --max 5000 # 正文全文
    python -m tools.library collections                  # 合集树
    python -m tools.library collection XYZ9876 --limit 50
    python -m tools.library tags                         # 标签及篇数
    python -m tools.library recent --days 30             # 最近 30 天

全部只读，一个字节都不会写进 Zotero。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.kernel.cli import flag, opt, pos, wants_help
from tools import library


def main():
    if wants_help():
        print(__doc__)
        return 0
    action = (pos(0) or 'stats').lower()

    if action in ('盘点', 'census'):
        from tools.library import census
        return census.main()

    if action in ('检索', 'find'):
        from tools.library import dbsearch
        if flag('--建索引') or flag('--reindex'):
            from tools.library import oaindex, teams
            out = oaindex.build(on_progress=lambda i, n, got: print(f'  取作者与摘要 {i}/{n}（拿到 {got}）'))
            print(f"作者索引：{out['n_found']} / {out['n_catalog_doi']} 篇")
            teams.build()
            print('团队对照已按新索引重挂')
            if not pos(1):
                return 0
        yr = opt('--年', '') or opt('--year', '')
        y1, _, y2 = yr.partition('-')
        rows, total = dbsearch.find(
            q=pos(1) or '', corr=opt('--通讯', '') or opt('--corr', ''), author=opt('--作者', '') or opt('--author', ''),
            team=opt('--团队', '') or opt('--team', ''), year_from=y1 or None, year_to=(y2 if '-' in yr else y1) or None,
            journal=opt('--刊', '') or opt('--journal', ''),
            has=[h for h in (opt('--有', '') or opt('--has', '')).replace('，', ',').split(',') if h],
            abstract=flag('--摘要') or flag('--abstract'), limit=int(opt('--n', 30)))
        print(dbsearch.render(rows, total))
        return 0

    if action in ('团队', 'teams'):
        from tools.library import teams
        roster = teams.load_roster()
        if flag('--重建') or flag('--rebuild'):
            out = teams.build(on_progress=lambda i, n, got: print(f'  取作者 {i}/{n}（拿到 {got}）'))
            print(f"写好 {len(out['papers'])} 篇的团队对照")
        links = teams.load_links()
        q = pos(1)
        if q:
            i = teams.find_team(roster, q)
            if i is None:
                print(f'名单里没有「{q}」（名单：data/state/teams.json）')
                return 1
            print(teams.render_team(roster, links, i))
        else:
            print(teams.render_list(roster, links))
        return 0

    if action in ('找', 'retrieve'):
        q = pos(1)
        if not q:
            print('用法：python -m tools.library 找 "要找的内容" [--n 8] [--si | --main]')
            return 2
        where = 'si' if flag('--si') else ('main' if flag('--main') else 'all')
        print(library.render_retrieve(library.retrieve(q, n=int(opt('--n', 8)), where=where), q))
        return 0

    if action in ('引文', 'refs'):
        key = pos(1)
        if not key:
            print('用法：python -m tools.library 引文 <文献id>')
            return 2
        print(library.render_refs(library.refs(key), key))
        return 0

    if action in ('库', 'db'):
        q = pos(1)
        if q:
            print(library.render_db(library.db_search(q, limit=int(opt('--limit', 25)))))
            return 0
        s = library.db_stats()
        print(f"证据库 {s['papers']} 篇（带 DOI {s['with_doi']}）· 有正文 {s['pdf']} · 有 SI {s['si']} · "
              f"已解析 {s['fulltext']}（SI {s['si_fulltext']}）· 已精读 {s['summary']} · "
              f"已结构化 {s['structured']} · 其中在 Zotero 的 {s['in_zotero']}")
        return 0

    if action == 'stats':
        s = library.stats()
        if not s['zotero_reachable']:
            print('Zotero 本地 API 不可达：请确认 Zotero 桌面已打开，且在'
                  '「设置 → 高级」里勾选了「允许其他应用与本机上的 Zotero 通信」。')
            return 1
        print(f"顶层条目 {s['top_items']} · 合集 {s['collections']} · 标签 {s['tags']}")
        return 0

    if action == 'search':
        items = library.search(query=pos(1), qmode='everything' if flag('--all')
                               else 'titleCreatorYear',
                               tag=opt('--tag'), item_type=opt('--type'),
                               collection=opt('--collection'),
                               limit=int(opt('--limit', 25)))
        print(library.render_items(items))
        return 0

    if action == 'item':
        key = pos(1)
        if not key:
            print('用法：python -m tools.library item <条目key>')
            return 2
        print(library.render_item(library.item(key)))
        return 0

    if action in ('units', '单元'):
        key = pos(1)
        if not key:
            print('用法：python -m tools.library 单元 <文献id> [--type fact]')
            return 2
        print(library.render_units(library.units(key, type_=opt('--type'))))
        return 0

    if action == 'pdf':
        key = pos(1)
        if not key:
            print('用法：python -m tools.library pdf <条目key>')
            return 2
        r = library.pdf(key)
        print(r['pdf_path'] or f'{key} 未找到正文 PDF（可能无 PDF 附件或只有补充材料）。')
        return 0 if r['pdf_path'] else 1

    if action == 'fulltext':
        key = pos(1)
        if not key:
            print('用法：python -m tools.library fulltext <条目key> [--max 20000]')
            return 2
        r = library.fulltext(key, max_chars=int(opt('--max', library.MAX_CHARS)))
        if not r['chars']:
            print(f"{key} 取不到全文：{r['why_empty']}")
            return 1
        print(r['text'])
        if r['truncated']:
            print('\n…（已截断，全文更长，可用 --max 调大）')
        return 0

    if action == 'collections':
        print(library.render_collections(library.collections()))
        return 0

    if action == 'collection':
        key = pos(1)
        if not key:
            print('用法：python -m tools.library collection <合集key> [--limit 25]')
            return 2
        print(library.render_items(library.collection_items(
            key, limit=int(opt('--limit', 25)))))
        return 0

    if action == 'tags':
        print(library.render_tags(library.tags()))
        return 0

    if action == 'recent':
        items = library.recent(days=int(opt('--days', 7)),
                               limit=int(opt('--limit', 25)))
        print(library.render_items(items))
        return 0

    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
