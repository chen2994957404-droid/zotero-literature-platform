# -*- coding: utf-8 -*-
"""host.watcher —— 主力机上的看门狗：常驻进程与端口服务的总管。

## 2026-10-13 起只剩看门狗

原来这里还有「打标签精读监听」（`service.py`：盯 Zotero 标签 → 精读 → 回写 Zotero），
随 Zotero 移出平台一起删了。精读改在文献库应用里按篇点（`host/app/runner.py`）。
旧代码在 git 标签 `zotero-before-removal`。

| 模块 | 是什么 | 怎么起 |
|---|---|---|
| `watchdog.py` | 看门狗：常驻进程真死了才重启，**绝不打断正在干活的**；按端口守 MCP 服务、取全文浏览器、文献库应用 | `python -m host.watcher.watchdog` |
| `host.ingest --loop` | 落地流水线常驻（另一个包；AUTO_BUILD=1 才拉） | 看门狗拉 |
| `host.daily` | 每日作业（另一个包；AUTO_BUILD=1 才拉） | 看门狗拉 |

日常由任务计划 `ZoteroLiteratureWatcher` 拉起**看门狗**（任务名是历史遗留，跑的就是看门狗）。
停任务停不掉它拉起的孙子进程（踩坑 #62），要用 `watchdog.kill_children()`。

## 两台机器

入口在 `main()` 里 `role.require_prod`：常驻服务只许在运行端跑。
"""
