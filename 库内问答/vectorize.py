# -*- coding: utf-8 -*-
"""向量化：扫 library 里所有文献的 full.md，切块，用 bge-m3 做 embedding，存入 Chroma。
遵守数据契约（读 library/<key>/full.md + meta.json）。
用法: python vectorize.py            增量向量化（只处理没入库的新文献）
      python vectorize.py --rebuild  清空重建整个向量库
"""
import os, sys, json

# 【标准开头】项目根加入 import 路径 + 强制 UTF-8 输出（详见 docs/代码规范_标准脚本模板.md）
_ROOT = os.path.dirname(os.path.abspath(__file__))
while True:
    if os.path.isdir(os.path.join(_ROOT, 'modules')):
        break                      # 项目根特征：modules/ 目录只在根存在
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        break                      # 到盘符根，兜底
    _ROOT = parent
sys.path.insert(0, _ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import chromadb
from modules.cli import flag
from modules.embed import embed, chunk as chunk_markdown

LIBRARY = os.path.join(_ROOT, 'workflow_data', 'library')
VECTOR_DB = os.path.join(_ROOT, 'workflow_data', 'vector_db')


def get_collection(rebuild):
    """打开向量库（持久化到本地文件）；rebuild 时先删掉旧集合再重建。"""
    client = chromadb.PersistentClient(path=VECTOR_DB)
    if rebuild:
        try:
            client.delete_collection('literature')
        except Exception:
            pass  # 集合不存在时删除会报错：反正马上要重建，忽略无害
    return client.get_or_create_collection('literature', metadata={'hnsw:space': 'cosine'})


def load_existing(coll):
    """读已入库的文献 key 集合（增量用）。"""
    existing = set()
    try:
        got = coll.get(include=['metadatas'])
        existing = {m['key'] for m in got['metadatas']}
    except Exception:
        pass  # 向量库为空/元数据缺失：按「没有已入库文献」处理，增量照常
    return existing


def vectorize_one(key, coll, existing):
    """向量化单篇：读 full.md → 切块 → embedding → 入库。返回 (是否新处理, 块数)。"""
    d = os.path.join(LIBRARY, key)
    md_path = os.path.join(d, 'parsed', 'full.md')
    meta_path = os.path.join(d, 'meta.json')
    if not os.path.isdir(d) or not os.path.exists(md_path):
        return False, 0
    if key in existing:
        print(f'[跳过] {key} 已入库')
        return False, 0
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, encoding='utf-8') as f:
            meta = json.load(f)
    title = meta.get('title', key)
    with open(md_path, encoding='utf-8') as f:
        md = f.read()
    chunks = chunk_markdown(md)
    if not chunks:
        return False, 0
    print(f'[处理] {title[:40]} — {len(chunks)} 块')
    # 批量 embedding（每批16块避免请求过大）
    ids, docs, metas = [], [], []
    for i, ch in enumerate(chunks):
        ids.append(f'{key}_{i}')
        docs.append(ch)
        metas.append({'key': key, 'title': title, 'doi': meta.get('DOI', ''), 'chunk': i})
    embs = []
    for b in range(0, len(docs), 16):
        embs.extend(embed(docs[b:b + 16]))
    coll.add(ids=ids, documents=docs, metadatas=metas, embeddings=embs)
    return True, len(chunks)


def main():
    """命令行入口：增量向量化，--rebuild 时清空重建整个向量库。"""
    rebuild = flag('--rebuild')
    os.makedirs(VECTOR_DB, exist_ok=True)
    coll = get_collection(rebuild)
    existing = set()
    if not rebuild:
        existing = load_existing(coll)

    total_chunks = 0
    processed = 0
    for key in sorted(os.listdir(LIBRARY)):
        ok, n = vectorize_one(key, coll, existing)
        if ok:
            total_chunks += n
            processed += 1

    print(f'\n完成：新处理 {processed} 篇文献，{total_chunks} 个文本块')
    print(f'向量库当前总块数：{coll.count()}')
    print(f'向量库位置：{VECTOR_DB}')


if __name__ == '__main__':
    main()
