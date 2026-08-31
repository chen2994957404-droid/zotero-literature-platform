# library · 这个工具特有的坑

> **全文在总账 `docs/incidents/踩坑记录.md`**（按编号找）。这里只留「跟本工具有关的那些」，
> 每条一句「对我意味着什么」——**改这个工具之前扫一眼，能省掉一整轮重新踩。**

| 坑号 | 现象 | 对本工具意味着什么 |
|---|---|---|
| #8 | Zotero 本地 API 只读，不能写 | 本工具是只读的，这不是限制而是定位 |
| #10 | Zotero API 限流 429 + 重复处理 | 批量查要限速 |
| #9 | 本地 API 请求被 PowerShell 拒 / curl 中文乱码 | 别用 shell 拼请求，走 `shared.adapters.zotero_client` |
| #43（第二个 43）| MCP 服务只把 stdout 设成 UTF-8，忘了 stdin —— 中文搜库全变乱码 | 本工具是 MCP 上最常被调的那个，中文搜索首当其冲 |

## 再踩到新的怎么办

1. 当场往 `docs/incidents/踩坑记录.md` 追加一条（编号 + 现象 + 根因 + 解法，三段齐全）
2. 如果它只跟本工具有关，同时在上面这张表里加一行
3. 写中文用 Python `io.open(..., encoding='utf-8')` 追加 —— 别用 PowerShell 重定向（GBK 乱码）

`docs/incidents/README.md` 是由各工具的本文件汇总生成的
（`python host/codegen/incidents.py`），别手改那一份。
