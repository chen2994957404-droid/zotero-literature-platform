# -*- coding: utf-8 -*-
"""轻量全库向量化：把 Zotero 里所有文献快速向量化（走Zotero全文API，不解析PDF、不占空间）。
用来"广撒网"建可搜索的文献库。与精读的高质量向量化(vectorize.py)共存于同一向量库。
用法: python vectorize_library.py            增量（只处理没入库的）
      python vectorize_library.py --rebuild  仅清空"全库轻量"来源的向量后重建
"""
import os, sys, json, urllib.request, time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from core import paths

from adapters import vectordb
from core.cli import flag
from core.config import need_site, get_site
from adapters.embed import embed, chunk
from adapters.zotero_client import get_fulltext

# 本机配置（Zotero 用户ID / 附件目录）统一从 core.config 读，换电脑只改 .env
_USER_ID = need_site('ZOTERO_USER_ID')
need_site('ZOTERO_STORAGE')        # 附件目录本脚本用不到，但按原行为仍要求已配置
LOCAL = get_site('ZOTERO_API_HOST') + '/api/users/' + _USER_ID
LH = {'Zotero-Allowed-Request': 'true'}
VECTOR_DB = paths.VECTOR_DB


def lget(path):
    """调 Zotero 本地 API（带允许头 + 20s 超时），返回 JSON。"""
    req = urllib.request.Request(LOCAL + path, headers=LH)
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def get_collection():
    """打开向量库。具体用哪家由 adapters.vectordb 决定。"""
    return vectordb.open_store()


def load_existing(coll):
    """已入库的 key 集合（避免重复；某 key 已有精读向量则跳过）。库为空返回空集合。"""
    return coll.existing_keys()


def fetch_top_items():
    """取 Zotero 所有顶层文献（分页，每页 100 条）。"""
    tops = []
    start = 0
    while True:
        d = lget(f'/items/top?limit=100&start={start}')
        if not d:
            break
        tops += d
        start += 100
        if len(d) < 100:
            break
    return tops


def vectorize_light(x, coll, existing):
    """轻量向量化单篇：找 PDF 附件 → 全文 → 切块 → 入库。

    返回 (结果, 块数)，结果 ∈ ('skipped' 已入库 / 'nofull' 无全文 / 'empty' 无块 / 'processed' 新入库)；
    取不到附件列表返回 (None, 0)（不计入任何统计）。
    """
    key = x['key']
    title = x['data'].get('title', key)
    if key in existing:
        return 'skipped', 0
    try:
        children = lget(f'/items/{key}/children')
    except Exception:
        return None, 0    # 该篇取不到附件列表（孤儿条目/服务抖动）：跳过且不计入统计，不影响其他文献
    att = None
    for c in children:
        if c['data'].get('contentType') == 'application/pdf':
            att = c['key']
            break
    if not att:
        return 'nofull', 0
    txt = get_fulltext(att)
    if len(txt) < 500:
        return 'nofull', 0
    chunks = chunk(txt)
    if not chunks:
        return 'empty', 0
    ids = [f'{key}_L{i}' for i in range(len(chunks))]
    metas = [{'key': key, 'title': title, 'doi': x['data'].get('DOI', ''),
              'source': 'library', 'chunk': i} for i in range(len(chunks))]
    embs = []
    for b in range(0, len(chunks), 16):
        embs.extend(embed(chunks[b:b + 16]))
    coll.add(ids, chunks, metas, embs)
    return 'processed', len(chunks)


def main():
    """命令行入口：增量轻量全库向量化（--rebuild 参数原脚本即声明但从未生效，保持该语义）。"""
    rebuild = flag('--rebuild')    # 原脚本只声明了该开关、从未使用（无清空逻辑），此处保持原行为不变
    os.makedirs(VECTOR_DB, exist_ok=True)
    coll = get_collection()
    existing = load_existing(coll)

    arts = [x for x in fetch_top_items()
            if x['data'].get('itemType') in ('journalArticle', 'conferencePaper', 'thesis', 'bookSection', 'book')]
    print(f'Zotero顶层文献 {len(arts)} 篇，开始轻量向量化...\n')

    processed = skipped = nofull = total_chunks = 0
    for x in arts:
        status, n = vectorize_light(x, coll, existing)
        if status == 'processed':
            processed += 1
            total_chunks += n
            print(f'[{processed}] {x["data"].get("title", x["key"])[:45]} — {n}块')
            time.sleep(0.2)
        elif status == 'skipped':
            skipped += 1
        elif status == 'nofull':
            nofull += 1
        # status 为 None（取不到附件列表）或 'empty'（无块）不计数，与原行为一致

    print(f'\n完成：新入库 {processed} 篇（{total_chunks}块），已有跳过 {skipped}，无全文 {nofull}')
    print(f'向量库总块数：{coll.count()}')


if __name__ == '__main__':
    main()
