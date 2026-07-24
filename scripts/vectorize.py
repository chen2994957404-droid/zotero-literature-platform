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

OLLAMA = 'http://localhost:11434/api/embed'
EMBED_MODEL = 'bge-m3'

def embed(texts):
    """批量取 embedding"""
    body = json.dumps({'model': EMBED_MODEL, 'input': texts}).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={'Content-Type': 'application/json'})
    r = json.loads(urllib.request.urlopen(req, timeout=300).read())
    return r['embeddings']

def strip_references(md):
    """截掉参考文献及之后的部分（References/Bibliography/参考文献/Supporting Information）。
    只保留正文，让向量检索聚焦研究内容。"""
    # 匹配作为标题或独立行出现的参考文献起始
    pat = re.compile(r'(?im)^\s*#{0,4}\s*(references|reference|bibliography|参考文献|literature\s+cited)\s*$')
    m = pat.search(md)
    cut = m.start() if m else len(md)
    # 也在正文里找 Supporting Information 标题（若更靠前也截）
    sm = re.search(r'(?im)^\s*#{1,4}\s*supporting\s+information\s*$', md)
    if sm and sm.start() < cut:
        cut = sm.start()
    body = md[:cut].strip()
    # 兜底：如果截得太狠（正文<20%），说明匹配错了，退回原文
    if len(body) < len(md) * 0.2:
        return md
    return body

def chunk_markdown(md, max_chars=800):
    """按段落切块，合并短段，控制在 max_chars 左右"""
    # 先去掉参考文献部分
    md = strip_references(md)
    # 去掉图片标记
    md = re.sub(r'!\[\]\(images/[^)]+\)', '', md)
    paras = [p.strip() for p in re.split(r'\n\s*\n', md) if p.strip()]
    chunks = []
    cur = ''
    for p in paras:
        if len(cur) + len(p) < max_chars:
            cur += ('\n' + p) if cur else p
        else:
            if cur:
                chunks.append(cur)
            # 超长段落再切
            if len(p) > max_chars:
                for i in range(0, len(p), max_chars):
                    chunks.append(p[i:i+max_chars])
                cur = ''
            else:
                cur = p
    if cur:
        chunks.append(cur)
    return chunks

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
