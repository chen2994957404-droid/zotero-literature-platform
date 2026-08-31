# -*- coding: utf-8 -*-
"""向量化：把文献变成可检索的向量块。**两条线，同一个向量库。**

| 线 | 料 | 覆盖 | 质量 | 入口 |
|---|---|---|---|---|
| 精层 `deep_all()`  | 精读产物 `parsed/full.md`（MineRU 解析的全文） | 只有精读过的 | 高 | `--deep` |
| 粗层 `light_all()` | Zotero 自带全文索引（不解析 PDF、不占空间） | **全库** | 一般 | `--light`（默认）|

两条并存不冲突：粗层负责「广撒网、都能搜到」，精层负责「读过的答得深」。
同一篇已有精层向量时，粗层会跳过（`existing_keys()` 判重）。

用法:
    python -m tools.ask.vectorize                 增量粗层（全库轻量，定时任务跑的就是这条）
    python -m tools.ask.vectorize --deep          增量精层（只处理精读过、还没入库的）
    python -m tools.ask.vectorize --deep --rebuild  清空重建整个向量库

R2/R3 窗合并自 `库内问答/{vectorize,vectorize_library}.py`。
"""
import io
import json
import os
import sys
import time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters import vectordb, zotero_client
from shared.adapters.embed import chunk, embed
from shared.kernel import paths, role
from shared.kernel.cli import flag

BATCH = 16          # 每批 16 块送 embedding，避免单次请求过大
ARTICLE_TYPES = ('journalArticle', 'conferencePaper', 'thesis', 'bookSection', 'book')


def get_collection(rebuild=False):
    """打开向量库；rebuild 时清空重建。用哪家向量库由 shared.adapters.vectordb 决定。"""
    return vectordb.open_store(rebuild=rebuild)


def _embed_all(texts):
    """分批向量化一串文本。"""
    out = []
    for b in range(0, len(texts), BATCH):
        out.extend(embed(texts[b:b + BATCH]))
    return out


# ── 精层：精读产物 full.md → 向量库 ────────────────────────────────────
def deep_one(key, coll, existing, log=print):
    """向量化单篇精读产物：读 full.md → 切块 → embedding → 入库。

    返回 (是否新处理, 块数)。没解析产物、或已入库，都返回 (False, 0)。
    """
    md_path = paths.fulltext(key)
    if not os.path.exists(md_path):
        return False, 0
    if key in existing:
        log(f'[跳过] {key} 已入库')
        return False, 0
    meta = {}
    if os.path.exists(paths.meta(key)):
        try:
            meta = json.load(io.open(paths.meta(key), encoding='utf-8'))
        except Exception:
            meta = {}          # meta 坏了不该毁掉整篇向量化，用 key 当标题
    title = meta.get('title', key)
    chunks = chunk(io.open(md_path, encoding='utf-8').read())
    if not chunks:
        return False, 0
    log(f'[处理] {title[:40]} — {len(chunks)} 块')
    ids = [f'{key}_{i}' for i in range(len(chunks))]
    metas = [{'key': key, 'title': title, 'doi': meta.get('DOI', ''), 'chunk': i}
             for i in range(len(chunks))]
    coll.add(ids, chunks, metas, _embed_all(chunks))
    return True, len(chunks)


def deep_all(rebuild=False, log=print):
    """精层增量向量化全库。返回 (处理篇数, 块数)。"""
    coll = get_collection(rebuild)
    existing = set() if rebuild else coll.existing_keys()
    processed = total_chunks = 0
    for key in paths.all_keys():
        ok, n = deep_one(key, coll, existing, log=log)
        if ok:
            processed += 1
            total_chunks += n
    log(f'\n完成：新处理 {processed} 篇文献，{total_chunks} 个文本块')
    log(f'向量库当前总块数：{coll.count()}')
    return processed, total_chunks


# ── 粗层：Zotero 全文索引 → 向量库 ────────────────────────────────────
def fetch_top_items():
    """取 Zotero 所有顶层文献（分页，每页 100 条）。走适配层，红线 #5。"""
    tops = []
    start = 0
    while True:
        d = zotero_client.search_items(limit=100, start=start)
        if not d:
            break
        tops += d
        start += 100
        if len(d) < 100:
            break
    return tops


def light_one(x, coll, existing):
    """轻量向量化单篇：找 PDF 附件 → 取全文索引 → 切块 → 入库。

    返回 (结果, 块数)，结果 ∈ ('skipped' 已入库 / 'nofull' 无全文 / 'empty' 无块 /
    'processed' 新入库)；取不到附件列表返回 (None, 0)（不计入任何统计）。
    """
    key = x['key']
    title = x['data'].get('title', key)
    if key in existing:
        return 'skipped', 0
    try:
        children = zotero_client.zget(
            f'/users/{zotero_client.USER_ID}/items/{key}/children')
    except Exception:
        return None, 0    # 该篇取不到附件列表（孤儿条目/服务抖动）：跳过且不计入统计
    att = None
    for c in children:
        if c['data'].get('contentType') == 'application/pdf':
            att = c['key']
            break
    if not att:
        return 'nofull', 0
    txt = zotero_client.get_fulltext(att)
    if len(txt) < 500:
        return 'nofull', 0
    chunks = chunk(txt)
    if not chunks:
        return 'empty', 0
    ids = [f'{key}_L{i}' for i in range(len(chunks))]
    metas = [{'key': key, 'title': title, 'doi': x['data'].get('DOI', ''),
              'source': 'library', 'chunk': i} for i in range(len(chunks))]
    coll.add(ids, chunks, metas, _embed_all(chunks))
    return 'processed', len(chunks)


def light_all(log=print):
    """粗层增量向量化全库（走 Zotero 全文 API）。返回 (处理篇数, 块数)。"""
    coll = get_collection()
    existing = coll.existing_keys()
    arts = [x for x in fetch_top_items()
            if x['data'].get('itemType') in ARTICLE_TYPES]
    log(f'Zotero顶层文献 {len(arts)} 篇，开始轻量向量化...\n')

    processed = skipped = nofull = total_chunks = 0
    for x in arts:
        status, n = light_one(x, coll, existing)
        if status == 'processed':
            processed += 1
            total_chunks += n
            log(f'[{processed}] {x["data"].get("title", x["key"])[:45]} — {n}块')
            time.sleep(0.2)
        elif status == 'skipped':
            skipped += 1
        elif status == 'nofull':
            nofull += 1
        # status 为 None（取不到附件列表）或 'empty'（无块）不计数

    log(f'\n完成：新入库 {processed} 篇（{total_chunks}块），'
        f'已有跳过 {skipped}，无全文 {nofull}')
    log(f'向量库总块数：{coll.count()}')
    return processed, total_chunks


def main():
    """命令行入口：默认粗层增量；--deep 走精层；--rebuild 清空重建（只对精层有意义）。"""
    # 机器角色守卫：这件事只允许在运行端（主力机）做，见 docs/两台机器的分工.md
    role.require_prod('全库向量化', force=flag('--force'))
    os.makedirs(paths.VECTOR_DB, exist_ok=True)
    if flag('--deep'):
        deep_all(rebuild=flag('--rebuild'))
        print(f'向量库位置：{paths.VECTOR_DB}')
    else:
        light_all()


if __name__ == '__main__':
    main()
