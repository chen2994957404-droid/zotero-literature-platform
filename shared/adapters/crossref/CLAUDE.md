# crossref · DOI 元数据

> 你可能是被单独选中这个积木文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这是什么

**一块「公理件」**：一个 DOI → 这篇文献的书目信息（标题/作者/期刊/年份/摘要），
以及把它摆成 Zotero 条目该有的样子。

## 职责

- 只做「问 Crossref 要元数据」和「字段对齐」这两件不可再分的事。
- **不写 Zotero**（那是 `zotero_client` 的活），**不决定要不要收**（那是工具层的活）。

## 为什么存在（2026-08-30 R3 窗建）

按 DOI 收文献这条线原本把 HTTP 请求直接写在 `找新文献/import_by_doi.py` 里，
是「联网只在 adapters」（红线 #5）的破口。红线守的是这个承诺：
**换掉外部服务只改一个文件**。元数据源以后想换成 DataCite / OpenAlex，
只需要在这里换实现，工具层一行不动。

## 对外接口

| 函数 | 说明 |
|---|---|
| `work(doi)` | → Crossref 的 message 字典；DOI 不存在抛 `DoiNotFound` |
| `to_zotero_item(m, tags=None)` | message → Zotero `journalArticle` 条目字典 |

两个异常分得很清楚：`DoiNotFound`（重试没用，跳过这条）
vs `CrossrefError`（对方抖动，可重试）。调用方据此决定批量作业是跳过还是重来。

## 谁在用

- `tools/discover/importer.py` —— 按 DOI 收进 Zotero

## 改完必须做

```
python shared/adapters/crossref/selftest.py     # 6 条离线 + 1 条联网（不通则 SKIP）
python -m pytest -q                              # 架构守卫
```
