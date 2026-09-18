# journalwatch · 这个工具特有的坑

> **全文在总账 `docs/incidents/踩坑记录.md`**（按编号找）。这里只留「跟本工具有关的那些」，
> 每条一句「对我意味着什么」——**改这个工具之前扫一眼，能省掉一整轮重新踩。**

| 坑号 | 现象 | 对本工具意味着什么 |
|---|---|---|
| #160 | Crossref `/journals?query=` 按名字搜刊会给错刊（"Nature" 搜出 NatureJobs，"Chem" 搜出 ChemInform） | 清单里的 ISSN 一律用 `/journals/<ISSN>` 逐个验过再写，别按名字搜 |

## 再踩到新的怎么办

1. 当场往 `docs/incidents/踩坑记录.md` 追加一条（编号 + 现象 + 根因 + 解法，三段齐全）
2. 如果它只跟本工具有关，同时在上面这张表里加一行
3. 写中文用 Python `io.open(..., encoding='utf-8')` 追加 —— 别用 PowerShell 重定向（GBK 乱码）

## #172（2026-09-18）`journalwatch_recent` 作为 MCP tool 永远跑不完
59 本刊串行问 Crossref 两分多钟，MCP 客户端 60 秒断。改成读雷达库（`recent_from_store`，0.04 秒），
现场巡逻仍走 `patrol()`。全文见 docs/incidents/踩坑记录.md #172。
