# semanticscholar · Semantic Scholar 学术图谱

> 你可能是被单独选中这个模块文件夹打开的。本文件是你的全部上下文。

## 这是什么

一个原子模块：DOI → S2 的记录（被引数、开放获取直链、TLDR）；DOI → 谁引了它、**怎么引的**（意图 + 那句话）。
后者是 Crossref / OpenAlex 都给不了的。

## 对外接口

| 函数 | 说明 |
|---|---|
| `papers(dois)` | 批量（500/次）→ `{doi: {title, abstract, tldr, citations, oa_pdf, published}}` |
| `citations(doi, limit)` | → `[{doi, title, year, intents, contexts}]` |
| `normalize(rec)` | 原始 JSON → 字典（纯函数） |

额度：key 每秒 1 次累计所有端点（模块内自己节流）；没 key 走公共池。key 名 `S2_API_KEY`。

## 谁在用

- `tools/journalwatch`：给雷达补被引数 / OA 直链 / TLDR，给过线文章补引用意图

## 改完必须做

```
python shared/adapters/semanticscholar/selftest.py
python -m pytest -q
```
