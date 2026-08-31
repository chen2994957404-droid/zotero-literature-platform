# vectordb · 向量库适配层 —— 给 LLM 的说明

## 是什么

把向量库（当前实现：Chroma）包在我们自己的接口后面。**属于 adapters 环**，
所以它是全平台唯一允许 `import chromadb` 的地方。

## 为什么存在

重构前 `import chromadb` 出现在 **5 个地方**，每处都自己建 client、自己写集合名、
自己解 Chroma 那套「每个字段套一层 list」的返回：

```python
res = coll.query(query_embeddings=[v], n_results=6, include=[...])
docs, metas = res['documents'][0], res['metadatas'][0]   # ← 这个 [0] 就是绑死的证据
```

换任何别的向量库，这 5 处每一处都要改，而且改错了不报错、只静默返回空结果。

## 接口（换实现时必须守住）

```python
from adapters import vectordb
store = vectordb.open_store()              # 或 open_store(rebuild=True)
store.add(ids, documents, metadatas, embeddings)
hits = store.query(qvec, n=6)              # → [{'id','doc','meta','distance','sim'}, ...]
store.existing_keys()                      # 增量入库用
store.count()
```

`sim` 统一是**「越大越像」**（cosine 距离取 1 减并夹到 0~1）。
调用方不该知道底层用的是距离还是相似度 —— 那正是这层要隔离的东西。

## 坑

- **Chroma 只接受 3~512 位 ASCII 集合名**，中文名会被直接拒（实测）。
- 换 embedding 模型必须**全量重建**：不同模型的向量在数学上不可比
  （见 `docs/reference/数据契约.md`）。重建是本地免费的，不构成障碍。

## 验证

```
python adapters/vectordb/selftest.py     # 临时目录 + 假向量，不碰真实数据
python -m pytest tests/test_adapters_vectordb.py
```
