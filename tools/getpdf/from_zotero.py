# -*- coding: utf-8 -*-
"""from_zotero · 把用户 Zotero 里已有的文献**回流**成本地正本（一次性，只读 Zotero）。

**为什么要有这一步**（2026-09-13 用户拍板）：证据库是全集，Zotero 是他自己挑出来读的
子集。可历史上文献是先进 Zotero 的 —— 两百多篇的 PDF 只躺在 Zotero 的 storage 里，
证据库那边只有精读过的几十篇有目录。要让「证据库 ⊇ Zotero」成立，得把这些搬一份过来。

做什么：逐条翻 Zotero 顶层条目 → 有正文附件的复制到 `raw/<Zotero编号>/main.pdf`、
SI 复制到 `raw/<Zotero编号>/si.*` → 登记 `curated/<Zotero编号>/meta.json`。
**不删 Zotero 里的任何东西，不写 Zotero。** 幂等：已经搬过的直接跳过。

用法（在有 Zotero 的那台机器上）：
    python -m tools.getpdf --从Zotero落地
    python -m tools.getpdf --从Zotero落地 --limit 20     # 先试 20 篇
"""
import os

from shared.adapters import zotero_client as zc
from shared.kernel import catalog, paths
from shared.kernel.log import get_logger

log = get_logger('getpdf')


def _meta_from_item(d):
    """Zotero 条目 → 目录字段（只取目录关心的那几样）。"""
    names = [((c.get('lastName') or '') + ' ' + (c.get('firstName') or '')).strip()
             for c in (d.get('creators') or [])]
    return dict(doi=d.get('DOI') or '', title=d.get('title') or '',
                year=(d.get('date') or '')[:4], journal=d.get('publicationTitle') or '',
                authors=[n for n in names if n][:20], source=catalog.SRC_ZOTERO,
                zotero_key=d.get('key') or '')


def land_one(item):
    """一条 Zotero 条目 → dict(key, pdf, si, action)。action ∈ landed / exists / nopdf。"""
    from tools.getpdf import _copy                  # 同一个工具包内
    d = item.get('data') or item
    key = paths.check_key(d['key'])
    out = {'key': key, 'pdf': '', 'si': '', 'action': 'nopdf', 'title': d.get('title') or ''}
    changed = False

    main = paths.local_pdf(key)
    if not os.path.exists(main):
        att = zc.find_pdf(key)
        if att and os.path.exists(att):
            changed |= _copy(att, main)
    if os.path.exists(main):
        out['pdf'] = main

    si = paths.find_local_si(key)
    if not si:
        src, kind = zc.find_si(key)
        if src and os.path.exists(src):
            dst = paths.local_si(key, kind or 'pdf')
            changed |= _copy(src, dst)
            si = dst
    out['si'] = si or ''

    if out['pdf'] or out['si']:
        catalog.register(key, **_meta_from_item(d))
        out['action'] = 'landed' if changed else 'exists'
    else:
        # 没附件的也登记元数据：它仍是用户库里的一篇，目录里该有名字
        catalog.register(key, **_meta_from_item(d))
    return out


def land_all(limit=None, log_fn=print, quiet=False):
    """全库回流 → 计数 dict。只读 Zotero；Zotero 没开会直接抛错（这是前提，不是意外）。

    `quiet=True`（每小时的增量同步用）只打印真落了新东西的，早就在的不刷屏。
    """
    counts = {'landed': 0, 'exists': 0, 'nopdf': 0, 'failed': 0}
    start, seen = 0, 0
    while True:
        page = zc.search_items(limit=100, start=start)
        if not page:
            break
        for it in page:
            d = it.get('data') or it
            if d.get('itemType') in ('attachment', 'note'):
                continue
            seen += 1
            try:
                r = land_one(it)
                counts[r['action']] += 1
                if r['action'] == 'landed' or not quiet:
                    mark = {'landed': '✓', 'exists': '=', 'nopdf': '·'}[r['action']]
                    log_fn(f'  {mark} {r["key"]}  {r["title"][:60]}'
                           + ('  +SI' if r['si'] else ''))
            except Exception as e:
                counts['failed'] += 1
                log_fn(f'  × {d.get("key")}  {type(e).__name__}: {str(e)[:80]}')
                log.info(f'{d.get("key")} 回流失败：{type(e).__name__}: {e}')
            if limit and seen >= limit:
                return counts
        if len(page) < 100:
            break
        start += 100
    return counts
