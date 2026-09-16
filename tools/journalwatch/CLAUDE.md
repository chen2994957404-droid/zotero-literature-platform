# journalwatch · 盯新刊

> 你可能是被单独选中这个模块文件夹打开的。本文件是你的全部上下文。

## 这是什么

一个工作流：读刊物清单 → 逐刊问 Crossref「这天之后新登记了什么」→ 标出证据库里有没有 →
记住见过的 → 列出来。**只列不取、不筛相关度**（2026-09-15 用户定：先把路打通，后面再定）。

## 文件

- `__init__.py`：`load_journals` / `fetch` / `annotate` / `patrol`
- `cli.py`：`python -m tools.journalwatch`；结果暂存成 `paths.last_search()` 格式，
  `tools.discover.collect` 能按编号收（两个工具**不互相 import**，只共用那个文件）
- `mcp.py`：`journalwatch_recent`（只读 tool，`confirm=True`）

## 改完必须做

```
python tools/journalwatch/selftest.py
python -m pytest -q tools/journalwatch
python host/doctor/health_check.py --offline
```
