# -*- coding: utf-8 -*-
"""轻量全库向量化：把 Zotero 里所有文献快速向量化（走Zotero全文API，不解析PDF、不占空间）。
用来"广撒网"建可搜索的文献库。与精读的高质量向量化(vectorize.py)共存于同一向量库。
用法: python vectorize_library.py            增量（只处理没入库的）
      python vectorize_library.py --rebuild  仅清空"全库轻量"来源的向量后重建
"""
import os, json, re, sys, urllib.request, time
import chromadb

USER_ID = '16078117'
LOCAL = 'http://localhost:23119/api/users/' + USER_ID
LH = {'Zotero-Allowed-Request': 'true'}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VECTOR_DB = os.path.join(ROOT, 'workflow_data', 'vector_db')
os.makedirs(VECTOR_DB, exist_ok=True)
REBUILD = '--rebuild' in sys.argv

# embedding/切块/去参考文献 + Zotero全文 已收敛到公理件
sys.path.insert(0, ROOT)
from modules.embed import embed, strip_references, chunk
from modules.zotero_client import get_fulltext

def lget(path):
    return json.loads(urllib.request.urlopen(urllib.request.Request(LOCAL + path, headers=LH), timeout=20).read())

client = chromadb.PersistentClient(path=VECTOR_DB)
coll = client.get_or_create_collection('literature', metadata={'hnsw:space': 'cosine'})

# 已入库的key（避免重复；精读的高质量版优先，若某key已有精读向量则跳过）
existing = set()
try:
    got = coll.get(include=['metadatas'])
    existing = {m['key'] for m in got['metadatas']}
except Exception:
    pass

# 取所有顶层文献
tops = []
start = 0
while True:
    d = lget(f'/items/top?limit=100&start={start}')
    if not d: break
    tops += d; start += 100
    if len(d) < 100: break

arts = [x for x in tops if x['data'].get('itemType') in ('journalArticle', 'conferencePaper', 'thesis', 'bookSection', 'book')]
print(f'Zotero顶层文献 {len(arts)} 篇，开始轻量向量化...\n')

processed = skipped = nofull = total_chunks = 0
for x in arts:
    key = x['key']
    title = x['data'].get('title', key)
    if key in existing:
        skipped += 1
        continue
    # 找PDF附件
    try:
        children = lget(f'/items/{key}/children')
    except Exception:
        continue
    att = None
    for c in children:
        if c['data'].get('contentType') == 'application/pdf':
            att = c['key']; break
    if not att:
        nofull += 1
        continue
    txt = get_fulltext(att)
    if len(txt) < 500:
        nofull += 1
        continue
    chunks = chunk(txt)
    if not chunks:
        continue
    ids = [f'{key}_L{i}' for i in range(len(chunks))]
    metas = [{'key': key, 'title': title, 'doi': x['data'].get('DOI', ''),
              'source': 'library', 'chunk': i} for i in range(len(chunks))]
    embs = []
    for b in range(0, len(chunks), 16):
        embs.extend(embed(chunks[b:b+16]))
    coll.add(ids=ids, documents=chunks, metadatas=metas, embeddings=embs)
    processed += 1; total_chunks += len(chunks)
    print(f'[{processed}] {title[:45]} — {len(chunks)}块')
    time.sleep(0.2)

print(f'\n完成：新入库 {processed} 篇（{total_chunks}块），已有跳过 {skipped}，无全文 {nofull}')
print(f'向量库总块数：{coll.count()}')
