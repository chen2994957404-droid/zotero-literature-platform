# -*- coding: utf-8 -*-
"""查库的命令行入口（只解析参数，一行业务逻辑都没有）。

用法:
    python -m tools.library 库                          # 证据库有多大（全集；Zotero 只是子集）
    python -m tools.library 库 硼                        # 按标题/DOI/期刊搜证据库（不联网）
    python -m tools.library 库 10.1021/acs.macromol.5b00210
    python -m tools.library stats                       # Zotero 统计 + 通不通
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
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel.cli import flag, opt, pos, wants_help
from tools import library


def main():
    if wants_help():
        print(__doc__)
        return 0
    action = (pos(0) or 'stats').lower()

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
