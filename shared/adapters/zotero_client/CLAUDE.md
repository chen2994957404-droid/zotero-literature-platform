# zotero_client · Zotero 接口

> 你可能是被单独选中这个积木文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这是什么

**一块「公理件」** —— 平台的最小可复用单元。整个项目的架构是：
公理件（原子能力）→ 定理（工作流）→ 组合。你现在在最底层。

**公理特征：只做一件不可再分的事。** 如果你想在这里加一个「顺便还做 XX」的功能，
那说明 XX 属于上层，不属于这里。保持这块的纯粹，是整个体系不腐坏的前提。

用户是材料方向研究者（聚硼硅氧烷/动态键弹性体），**不懂编程**。
技术决策你自己拿主意，跟他汇报用大白话。

## 职责

跟 Zotero 打交道：查条目、定位正文 PDF、取全文。

## 对外接口

| 函数 | 用途 |
|---|---|
| `zget(path)` | 调 Zotero 本地 API（`localhost:23119`） |
| `find_pdf(item_key)` | 找该文献的**正文** PDF（智能排除补充材料） |
| `get_fulltext(att_key)` | 取附件全文 |
| `counts()` / `count_of(path)` | 库有多大（条数在**响应头** Total-Results 里，是 Zotero 自己的怪癖）|
| `item(key)` / `children(key)` | 单条目 / 它的附件与笔记（走本地 API，与走云端的 `get_item` 不是一回事）|
| `collections()` / `collection_items()` / `tags()` / `recent_items()` | 合集 / 合集内文献 / 标签 / 最近改动 |
| `simplify(item)` | Zotero 条目 → 扁平 dict（`creators` 那套形状是它的，不该漏给上层）|

R4 窗（2026-08-31）从 `host/mcp/zotero_server.py` 收进来的那一批：那边原来自己拼 `/users/<id>/collections?...` 这类路径、自己 urlopen 读响应头，是「联网只在 adapters」的破口。**API 路径长什么样只该有这一处知道。**

## find_pdf 的判别逻辑（别改坏）

1. **最优先**：附件标题为 `Full Text PDF`（Zotero 规范命名，最可靠，不靠猜）
2. 兜底：排除补充材料后选最大的文件

补充材料的识别特征包括 `suppmat/supporting/supplement/-si-/_si_/appendix`，
以及 **`MOESM`/`_ESM`**（Springer/Nature 系的标准命名 —— 漏了这个曾把 SI 当正文精读）。

## 注意

- Zotero 桌面程序必须开着，本地 API 才通。
- 用户ID 和附件目录来自 `config.get_site()`，**不要写死**。

## 谁在用它

精读线（找 PDF）、抽取线、找新文献线、库房维护。

改这里的对外接口 = 可能弄坏上面所有调用者。**改签名前先想清楚兼容性。**

## 改完必须做

```
python selftest.py                       # 本块自测，必须全过
python ../../平台管理/health_check.py     # 全局体检，确认没碰坏别人
```
自测不过就是没改完。**没有自测覆盖的新功能，等于没写。**
