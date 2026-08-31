# -*- coding: utf-8 -*-
"""curate · 库房维护：让 Zotero 库和平台产物保持整齐、一致、不掉队。

这不是「科研能力」，是**管家**：没人主动想用它，但它不干活，
别的工具就会在脏数据上产出错答案（缺 meta 的文献进不了对比表、
重复条目让去重白做、附件命名不规范让精读找不到正文 PDF）。

**五条线，各管一件事**（每条都可以单独跑、都能中断续跑）：

| 线 | 干什么 | 花钱 | 写 Zotero |
|---|---|---|---|
| `sync`     | 定时增量同步：新文献自动进向量库 + 进对比表 | 否（全本地）| 否 |
| `junk`     | 找出无 PDF 的残留条目 → 确认后删 | 否 | **删条目** |
| `rename`   | 附件统一命名（正文 / SI / 快照）| 否 | **改附件名** |
| `backfill` | 给缺 `meta.json` 的文献补元数据 | 否 | 否 |
| `tags`     | 标签改造（`dim:value` → `dim/value`）；`autotag` 已弃用 | 是（autotag）| **改标签** |

**除 `sync`/`backfill` 外都写用户的真实 Zotero 库**，一律带机器角色守卫：
A 机（编程端 `ROLE=dev`）默认拒绝执行，见 docs/howto/两台机器的分工.md。

对外接口：每条线一个模块，各自的 `main()` 就是命令行入口：

    python -m tools.curate.sync          定时任务每小时跑的就是这条
    python -m tools.curate.junk          列清单（不删）
    python -m tools.curate.junk --删除    按清单删（危险，先看清单）
    python -m tools.curate.rename <全库json> [apply]
    python -m tools.curate.backfill
    python -m tools.curate.tags [apply]

依赖：shared.adapters.zotero_client（唯一碰 Zotero 的一环）+ shared.kernel。
"""
