# journalwatch · 盯新刊

> 你可能是被单独选中这个模块文件夹打开的。本文件是你的全部上下文。

## 这是什么

一个工作流：读刊物清单 → 逐刊问 Crossref「这天之后新登记了什么」→ 标出证据库里有没有 →
记住见过的 → **存进雷达库**（0 级：题目/摘要/参考文献）→ 列出来。**只列不取、不筛相关度**
`host/watcher` 每天跑一次 `patrol`；`--回填 3` 一次性把三年拉进雷达。（2026-09-15 用户定：先把路打通，后面再定）。

## 文件

- `__init__.py`：`load_journals` / `fetch` / `annotate` / `patrol` / `backfill` / `refresh`
  补摘要：`fill_abstracts`（OpenAlex）→ `fill_from_s2`（Semantic Scholar，顺带被引数与 OA 直链）
  升 1 级队列：`enqueue_passing` / `enqueue_recent` / `next_to_harvest` / `mark_harvest`（取件由 host/watcher 做）
- `store.py`：雷达库（SQLite，`paths.radar_db()`）：works + refs；`upsert` / `stats` / `cited_in_library`
- `cli.py`：`python -m tools.journalwatch`；结果暂存成 `paths.last_search()` 格式，
  `tools.discover.collect` 能按编号收（两个工具**不互相 import**，只共用那个文件）
- `mcp.py`：`journalwatch_recent`（只读 tool，`confirm=True`）

## 改完必须做

```
python tools/journalwatch/selftest.py
python -m pytest -q tools/journalwatch
python host/doctor/health_check.py --offline
```
