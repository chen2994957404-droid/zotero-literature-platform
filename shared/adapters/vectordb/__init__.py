# -*- coding: utf-8 -*-
"""shared.adapters.vectordb —— 向量库（当前实现：Chroma）。

**为什么要包这一层**（见 docs/架构重构_v2总体设计.md 阶段 2 第 10 项）：

重构前 `import chromadb` 出现在 **5 个地方**（ask / vectorize / vectorize_library /
brainstorm / lib_match），每处都自己 `PersistentClient(...)`、自己写
`get_or_create_collection('literature', {'hnsw:space': 'cosine'})`、
自己解 Chroma 那套「每个字段都套一层 list」的返回格式：

```python
res = coll.query(query_embeddings=[v], n_results=6, include=[...])
docs, metas = res['documents'][0], res['metadatas'][0]      # ← 这个 [0] 就是绑死的证据
```

那个 `[0]` 是 Chroma 特有的形状。换任何别的向量库，这 5 处**每一处都要改**，
而且改错了不会报错，只会静默返回空结果。

包上之后：**换向量库 = 改这一个文件**（数据契约里也早写着「向量库是可随时重建的
派生层，是最不值钱也最容易换的一层」）。

## 用法

```python
from shared.adapters import vectordb

store = vectordb.open_store()               # 默认库，默认集合
store = vectordb.open_store(rebuild=True)   # 先清空再建（重新向量化时用）

store.add(ids, documents, metadatas, embeddings)
hits = store.query(qvec, n=6)               # → [Hit, ...]，已经拆好，没有 [0]
store.count()
store.all_metadatas()                       # 增量入库时用来看哪些已经有了
```

`query` 返回的每个 `Hit` 是一个普通 dict：

    {'id': ..., 'doc': 正文块, 'meta': {...}, 'distance': 0.21, 'sim': 0.79}

`sim` 是我们统一定义的「越大越像」（cosine 距离取 1 减），
调用方不必知道底层用的是距离还是相似度 —— 这正是这一层要隔离的东西。

## 换实现时要守住的契约

1. `open_store()` 返回的对象有 add / query / count / all_metadatas / reset
2. `query` 返回 `Hit` 列表，字段名不变，`sim` 越大越像
3. 集合名与向量空间由本模块决定，调用方不需要知道

⚠ 换 embedding 模型必须全量重建：不同模型的向量在数学上不可比
（见 `docs/数据契约.md`）。重建是本地免费的，所以这不构成障碍。
"""
import os

from shared.kernel import errors, paths

COLLECTION = 'literature'        # 集合名：全平台只有这一个
SPACE = 'cosine'                 # 向量空间：与 embed 模型（bge-m3）配套


class Store:
    """一个向量集合。对外只暴露我们自己定义的几个动作。"""

    def __init__(self, path=None, name=COLLECTION, rebuild=False):
        self.path = path or paths.VECTOR_DB
        self.name = name
        self._coll = self._open(rebuild)

    def _open(self, rebuild):
        try:
            import chromadb                      # 只在这一层 import
        except ImportError as e:
            raise errors.ServiceUnavailable(
                f'向量库依赖没装好（chromadb）：{e}。装：pip install -r requirements.txt',
                service='vectordb') from e
        try:
            client = chromadb.PersistentClient(path=self.path)
            if rebuild:
                try:
                    client.delete_collection(self.name)
                except Exception:
                    pass        # 集合本来就不存在时删除会报错，反正马上要重建
            return client.get_or_create_collection(
                self.name, metadata={'hnsw:space': SPACE})
        except Exception as e:
            raise errors.ServiceUnavailable(
                f'打不开向量库 {self.path}：{e}', service='vectordb') from e

    # ── 写 ──
    def add(self, ids, documents, metadatas, embeddings):
        """批量入库。四个列表必须等长。"""
        n = len(ids)
        if not (len(documents) == len(metadatas) == len(embeddings) == n):
            raise errors.BadInputError(
                f'入库的四个列表长度不一致：ids={n}、docs={len(documents)}、'
                f'metas={len(metadatas)}、embs={len(embeddings)}')
        if n == 0:
            return 0
        self._coll.add(ids=ids, documents=documents,
                       metadatas=metadatas, embeddings=embeddings)
        return n

    def reset(self):
        """清空并重建集合（换 embedding 模型时用）。"""
        self._coll = self._open(rebuild=True)

    # ── 读 ──
    def query(self, embedding, n=6, where=None):
        """按向量检索，返回 Hit 列表（已经拆平，没有 Chroma 那层 [0]）。

        找不到就返回空列表 —— 调用方不必区分「没有结果」和「出错了」。
        """
        if n <= 0:
            return []
        try:
            res = self._coll.query(
                query_embeddings=[list(embedding)], n_results=n, where=where,
                include=['documents', 'metadatas', 'distances'])
        except Exception as e:
            raise errors.ExternalServiceError(f'向量检索失败：{e}', service='vectordb') from e
        return _to_hits(res)

    def all_metadatas(self):
        """全部条目的元数据（增量入库时用来看哪些 key 已经有了）。

        库为空或元数据缺失时返回空列表，不抛错。
        """
        try:
            got = self._coll.get(include=['metadatas'])
            return [m for m in (got.get('metadatas') or []) if m]
        except Exception:
            return []

    def existing_keys(self, field='key'):
        """已入库的文献 key 集合（增量向量化的核心判断）。"""
        return {m[field] for m in self.all_metadatas() if m.get(field)}

    def count(self):
        try:
            return self._coll.count()
        except Exception:
            return 0


def _to_hits(res):
    """把 Chroma 那套「每个字段套一层 list」的返回，拆成普通的 Hit 列表。

    **这个函数就是本适配层存在的理由**：这层形状是 Chroma 特有的，
    换库时只有这里需要重写。
    """
    ids = (res.get('ids') or [[]])[0]
    docs = (res.get('documents') or [[]])[0]
    metas = (res.get('metadatas') or [[]])[0]
    dists = (res.get('distances') or [[]])[0]
    hits = []
    for i in range(len(ids)):
        d = dists[i] if i < len(dists) else None
        hits.append({
            'id': ids[i],
            'doc': docs[i] if i < len(docs) else '',
            'meta': (metas[i] if i < len(metas) else None) or {},
            'distance': d,
            # 统一成「越大越像」，调用方不必知道底层是距离还是相似度
            'sim': None if d is None else round(max(0.0, min(1.0, 1.0 - float(d))), 4),
        })
    return hits


def open_store(path=None, name=COLLECTION, rebuild=False):
    """打开（必要时创建）一个向量集合。"""
    return Store(path=path, name=name, rebuild=rebuild)


def exists(path=None):
    """向量库目录在不在（体检用，不触发 chromadb 导入）。"""
    return os.path.isdir(path or paths.VECTOR_DB)
