# -*- coding: utf-8 -*-
"""向量化：扫 library 里所有文献的 full.md，切块，用 bge-m3 做 embedding，存入 Chroma。
遵守数据契约（读 library/<key>/full.md + meta.json）。
用法: python vectorize.py            增量向量化（只处理没入库的新文献）
      python vectorize.py --rebuild  清空重建整个向量库
"""
import os, json, re, sys, urllib.request
import chromadb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBRARY = os.path.join(ROOT, 'workflow_data', 'library')
VECTOR_DB = os.path.join(ROOT, 'workflow_data', 'vector_db')
os.makedirs(VECTOR_DB, exist_ok=True)
REBUILD = '--rebuild' in sys.argv

# embedding/切块/去参考文献 已收敛到公理件 modules/embed
sys.path.insert(0, ROOT)
from modules.embed import embed, strip_references, chunk as chunk_markdown

# 连接 Chroma（持久化到本地文件）
client = chromadb.PersistentClient(path=VECTOR_DB)
if REBUILD:
    try: client.delete_collection('literature')
    except Exception: pass
coll = client.get_or_create_collection('literature', metadata={'hnsw:space': 'cosine'})

# 已入库的文献key（增量用）
existing = set()
if not REBUILD:
    try:
        got = coll.get(include=['metadatas'])
        existing = {m['key'] for m in got['metadatas']}
    except Exception:
        pass

total_chunks = 0
processed = 0
for key in sorted(os.listdir(LIBRARY)):
    d = os.path.join(LIBRARY, key)
    md_path = os.path.join(d, 'parsed', 'full.md')
    meta_path = os.path.join(d, 'meta.json')
    if not os.path.isdir(d) or not os.path.exists(md_path):
        continue
    if key in existing:
        print(f'[跳过] {key} 已入库')
        continue
    # 读元数据
    meta = {}
    if os.path.exists(meta_path):
        meta = json.load(open(meta_path, encoding='utf-8'))
    title = meta.get('title', key)
    md = open(md_path, encoding='utf-8').read()
    chunks = chunk_markdown(md)
    if not chunks:
        continue
    print(f'[处理] {title[:40]} — {len(chunks)} 块')
    # 批量 embedding（每批16块避免请求过大）
    ids, docs, metas, embs = [], [], [], []
    for i, ch in enumerate(chunks):
        ids.append(f'{key}_{i}')
        docs.append(ch)
        metas.append({'key': key, 'title': title, 'doi': meta.get('DOI', ''), 'chunk': i})
    for b in range(0, len(docs), 16):
        batch = docs[b:b+16]
        vecs = embed(batch)
        embs.extend(vecs)
    coll.add(ids=ids, documents=docs, metadatas=metas, embeddings=embs)
    total_chunks += len(chunks)
    processed += 1

print(f'\n完成：新处理 {processed} 篇文献，{total_chunks} 个文本块')
print(f'向量库当前总块数：{coll.count()}')
print(f'向量库位置：{VECTOR_DB}')
