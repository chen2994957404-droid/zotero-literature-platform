---
name: discover
description: 找新文献：拆检索式 + 雪球扩展 + 按「跟我多相关」排序。什么时候用：用户说「帮我找 XX 方向的文献」「补充点 XX 的文献」「这个问题有人做过吗」；要的是一份该读的清单，而且希望知道哪些已经在他库里
---

<!-- 本文件由 host/codegen/skills.py 生成，**别手改**。改源：tools/discover/SKILL.md + tools/discover/tool.toml -->

> **动手之前先看这三行**（取自 `tools/discover/tool.toml`）：
> **会花钱** · **有副作用**：写Zotero（按 DOI 导入） · **只能在运行端（主力机）跑**
> MCP 暴露方式：`prompt`（**由人在客户端点，模型不能自己发起**）
> 命令行：`python -m tools.discover`

# discover —— 找新文献

## 什么时候用我

- 用户说「帮我找 XX 方向的文献」「补充点 XX 的文献」「这个问题有人做过吗」
- 要的是**一份该读的清单**，而且希望知道哪些已经在他库里

## 怎么用

我是 **prompt**（拆检索式花钱，导入会写 Zotero）。讲清代价、用户点头后：

```
python -m tools.discover "关键词或一句话需求" [--解决问题] [--since 2020] [--openalex]
```

**收取是第二步，必须单独确认**：把清单给用户看，他说要 1、3、5 → 
`python -m tools.discover.collect 1,3,5`。别自作主张全导进去。

只想要一份简单列表、不要雪球和排序 → 直接 `tools.discover.search(query)`。

## 什么时候**别**用我

- **要一段回答而不是列表** → `askworld`（带出处作答）
- **搜的是用户自己的库** → `library_search`（免费）或 `ask`
- **已经有 DOI，只是想导进去** → `python -m tools.discover.importer <DOI>`，别绕一圈检索
- **要系统看清一个方向的版图**（谁是主流、聚成几簇、空白在哪）→ `direction_map`

## 边界

- 我只负责找和排序；**导入 Zotero 是写操作**，只在主力机上能跑
- 「跟我多相关」是拿用户库里的内容算的：库很空时这个排序没什么意义
- 默认会过滤掉贴题度低的；召回明显不足时可以 `--宽松`
