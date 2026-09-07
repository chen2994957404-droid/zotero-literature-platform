# -*- coding: utf-8 -*-
"""向量化：把文献变成可检索的向量块。**两条线，同一个向量库。**

| 线 | 料 | 覆盖 | 质量 | 入口 |
|---|---|---|---|---|
| 精层 `deep_all()`  | 精读产物 `parsed/full.md` **+ `si_parsed/full.md`（SI）** | 只有精读过的 | 高 | `--deep` |
| 粗层 `light_all()` | Zotero 自带全文索引（不解析 PDF、不占空间） | **全库** | 一般 | `--light`（默认）|

两条并存不冲突：粗层负责「广撒网、都能搜到」，精层负责「读过的答得深」。
**同一篇不会两档并存**：粗层遇到已有向量的跳过；精层入库后，反过来把同篇的粗层块删掉。

⚠ 判重必须按「这一档有没有入过库」算（`_indexed_keys(coll, source)`），
不能按「这篇有没有块」（`existing_keys()`）算 —— 粗层每小时自动跑、早把全库入过一遍，
用后者会让精层一篇都进不来，而且不报错（踩坑 #126）。

用法:
    python -m tools.ask.vectorize                 增量粗层（全库轻量，定时任务跑的就是这条）
    python -m tools.ask.vectorize --deep          增量精层（正文 + 补充材料 SI）
    python -m tools.ask.vectorize --deep --no-si  只做正文，跳过 SI
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

    入库成功后会把同一篇的**粗层块删掉** —— 同一篇不该两档并存。
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
    metas = [{'key': key, 'title': title, 'doi': meta.get('DOI', ''),
              'source': 'main', 'chunk': i} for i in range(len(chunks))]
    coll.add(ids, chunks, metas, _embed_all(chunks))
    # 精层进来了，同一篇的粗层块就该退场：它们讲同一件事，但那份是 Zotero 全文索引
    # 抽的，质量低一档，留着只会跟精层互相挤占检索名额。
    dropped = coll.delete_by(key=key, source='library')
    if dropped > 0:
        log(f'       同篇粗层 {dropped} 块退场（精层已就位）')
    return True, len(chunks)


# ── 判重：按「这一档有没有入过库」算，不按「这篇有没有块」算 ──────────
def _indexed_keys(coll, source):
    """已经把某一档（main / si / library）入过库的文献 key。

    **不能用 `existing_keys()`**：那个只回答「这篇有没有任何块」。
    粗层每小时自动跑、早把全库都入过一遍，于是拿它判重会让精层**一篇都进不来** ——
    而且不报错，只是安静地全部「跳过」。2026-09-06 实测的账：42 篇有 `full.md`，
    精层却只有 276 块（踩坑 #126）。SI 早先栽的是同一个跟头，解法也是同一个。
    """
    return {m.get('key') for m in coll.all_metadatas() if m.get('source') == source}


def _si_indexed_keys(coll):
    """已经把 SI 入过库的文献 key（`_indexed_keys` 的具名特例）。"""
    return _indexed_keys(coll, 'si')


# ── 精层·补充材料：si_parsed/full.md → 向量库 ─────────────────────────
def si_one(key, coll, existing_si, log=print):
    """向量化单篇的**补充材料**：读 si_parsed/full.md → 切块 → 入库。

    与 `deep_one` 同构，两处刻意不同：
      - id 用 `<key>_SI<i>`，与正文的 `<key>_<i>`、粗层的 `<key>_L<i>` 都不撞
      - meta 里 `source='si'`，`ask` 据此在答案里标明「出自补充材料」——
        否则用户拿着出处去正文里找，会找不到（SI 是另一个文件）

    返回 (是否新处理, 块数)。没有 SI、或已入库，都返回 (False, 0)。
    """
    si_path = paths.si_fulltext(key)
    if not os.path.exists(si_path):
        return False, 0
    if key in existing_si:
        return False, 0
    meta = {}
    if os.path.exists(paths.meta(key)):
        try:
            meta = json.load(io.open(paths.meta(key), encoding='utf-8'))
        except Exception:
            meta = {}
    title = meta.get('title', key)
    chunks = chunk(io.open(si_path, encoding='utf-8').read())
    if not chunks:
        return False, 0
    log(f'[SI]   {title[:40]} — {len(chunks)} 块')
    ids = [f'{key}_SI{i}' for i in range(len(chunks))]
    metas = [{'key': key, 'title': title, 'doi': meta.get('DOI', ''),
              'source': 'si', 'chunk': i} for i in range(len(chunks))]
    coll.add(ids, chunks, metas, _embed_all(chunks))
    return True, len(chunks)


def deep_all(rebuild=False, log=print, with_si=True):
    """精层增量向量化全库：**正文 + 补充材料**。返回 (处理篇数, 块数)。

    ⚠ 三档的判重都**按 source 分开算**（`_indexed_keys`）。用「这篇有没有块」判重时，
    精层会被早就入库的粗层挡在门外、SI 会被正文挡在门外 —— 都是安静地什么都不发生。
    """
    coll = get_collection(rebuild)
    existing = set() if rebuild else _indexed_keys(coll, 'main')
    existing_si = set() if rebuild else (_si_indexed_keys(coll) if with_si else set())
    processed = total_chunks = si_papers = si_chunks = 0
    for key in paths.all_keys():
        ok, n = deep_one(key, coll, existing, log=log)
        if ok:
            processed += 1
            total_chunks += n
        if with_si:
            ok_si, n_si = si_one(key, coll, existing_si, log=log)
            if ok_si:
                si_papers += 1
                si_chunks += n_si
    log(f'\n完成：正文新处理 {processed} 篇（{total_chunks} 块）'
        + (f'；补充材料新处理 {si_papers} 篇（{si_chunks} 块）' if with_si else ''))
    log(f'向量库当前总块数：{coll.count()}')
    return processed + si_papers, total_chunks + si_chunks


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
    # 机器角色守卫：这件事只允许在运行端（主力机）做，见 docs/howto/两台机器的分工.md
    role.require_prod('全库向量化', force=flag('--force'))
    os.makedirs(paths.VECTOR_DB, exist_ok=True)
    if flag('--deep'):
        deep_all(rebuild=flag('--rebuild'), with_si=not flag('--no-si'))
        print(f'向量库位置：{paths.VECTOR_DB}')
    else:
        light_all()


if __name__ == '__main__':
    main()
