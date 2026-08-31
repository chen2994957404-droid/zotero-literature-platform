# library —— 查用户的 Zotero 库

## 什么时候用我

- 用户问「我库里有没有 XX」「最近加了什么」「有哪些标签/合集」
- 你需要某篇的 **Zotero key**、正文 PDF 路径、或正文文本，好去做别的事
- 你想在花钱之前先确认这篇在不在库里、有没有 PDF

我是**唯一**一个你可以自己随便调的工具切片：只读、免费、不改任何东西。

## 怎么用

MCP 工具（可直接调）：

| 工具 | 用途 |
|---|---|
| `library_stats` | 库多大、Zotero 通不通（**排障第一步**）|
| `library_search` | 按 query/tag/itemType/collection 搜；`qmode=everything` 连全文搜 |
| `library_item` | 单篇元数据 + 附件 + 正文 PDF 路径 |
| `library_pdf` / `library_fulltext` | 拿 PDF 路径 / 拿全文文本 |
| `library_collections` / `library_collection_items` / `library_tags` | 合集与标签 |
| `library_recent` | 最近 N 天 |

命令行同名动作见 README。

## 什么时候**别**用我

- **要一段中文的、综合多篇的回答** → 用 `ask`（我只给条目列表和原始文本，不作答）
- **要比较性能数值**（拉伸强度、模量、自修复效率）→ 用 `paperdb`；
  我这里的全文是没结构的大段文字，你自己从里面读数字既慢又容易读错
- **库里没有、要去全世界找** → `discover`（找新文献）或 `askworld`（要带出处的回答）
- **要「精读」一篇**（中文图文报告）→ `deepread`。我给的 `library_fulltext`
  是 Zotero 的全文索引，**没有版面、没有图、公式经常是乱的**，不能拿它冒充精读
- **要改库**（打标签、改名、删条目）→ `curate`，而且必须先给用户看清单

## 边界

- 取不到全文很正常（没建索引、或扫描件没文本层），返回里会说明原因，别当成故障
- Zotero 本地 API 只监听 localhost：**只有用户主力机上跑得通**，编程端连不上是预期的
