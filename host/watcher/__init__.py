# -*- coding: utf-8 -*-
"""host.watcher —— 「打个标签就全自动」的那条常驻服务。

## 它为什么住在 host/ 而不是 tools/deepread/（R7 窗的判定）

R2 窗把它放在 `tools/deepread/watcher.py`，照的是 REBUILD.md 第四节的映射表。
但它做的事横跨两个工具：**精读一篇（deepread）之后顺手粗抽一遍（extract）**，
于是产生了全仓库唯一一处 `tools` import `tools` —— 违反第三节硬规则 2
（工具隔离：`tools/*` 不许 import 别的 `tools/*`）。

R7 窗按「规则优先于映射表」（同 R3/R4/R5/R6 的先例）把它挪到这里，判据是
REBUILD.md 第一节对 host 的定义本身：**host 不是能力，是让平台活着的东西。**
一个盯着 Zotero 标签、把两个工具串起来、由任务计划自启的守护进程，
正是这个定义。而硬规则 4 明写「`host/` 可以 import 一切」——
跨工具的编排本来就该发生在这一层。

## 一个看门狗，三个干活的进程（2026-09-17 起）

| 模块 | 是什么 | 怎么起 |
|---|---|---|
| `watchdog.py` | 看门狗：下面三个真死了才重启，**绝不打断正在干活的** | `python -m host.watcher.watchdog` |
| `service.py`  | 精读监听：发现标签 → 精读 → 回写 Zotero → 改标签（**只做这一件**；2026-09-23 起不再顺手跑老的整篇抽取，数值与整篇字段归落地流水线） | `python -m host.watcher.service` |
| `host.ingest --loop` | 落地流水线常驻（另一个包） | 看门狗拉 |
| `host.daily` | 每日作业：盯新刊 + 补摘要 + 升 1 级取件（另一个包，一天一次） | 看门狗拉 |

日常由任务计划 `ZoteroLiteratureWatcher` 拉起**看门狗**，看门狗再 spawn 出三个
干活的 —— 所以停任务停不掉它们（孙子进程，踩坑 #62），要用 `watchdog.kill_children()`。

## 两台机器

两个入口都在 `main()` 里 `role.require_prod`：常驻服务只许在运行端跑。
两台同时跑 = 重复精读同一篇、重复烧钱、标签状态机互相打架。
"""
