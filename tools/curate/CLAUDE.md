# tools/curate · 库房维护 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。

## 这块是什么

**管家**：让 Zotero 库和平台产物保持整齐、一致、不掉队。
没人主动想用它，但它不干活，别的工具就会在脏数据上产出错答案 ——
缺 `meta.json` 的文献进不了对比表、重复条目让去重白做、
附件命名乱掉会让精读**把补充材料当正文读**。

用户是材料方向研究者（聚硼硅氧烷/动态键弹性体），**不懂编程**。

## ⚠ 这里大部分动作会**写用户的真实 Zotero 库**

删条目、改附件名、改标签 —— 都是同步到用户所有设备、不可撤销的。
每个入口都带机器角色守卫：A 机（编程端 `ROLE=dev`）默认拒绝执行。
要在编程端试，用测试账号那一档（`ROLE=test`）。见 `two-machines` skill。

## 五条线

| 文件 | 干什么 | 花钱 | 写 Zotero |
|---|---|---|---|
| `sync.py` | 定时增量同步：新文献自动进向量库 + 进对比表 | 否 | 否 |
| `junk.py` | 找出无 PDF 的残留条目 → 确认后删 | 否 | **删条目** |
| `rename.py` | 附件统一命名（正文 / SI / 快照）| 否 | **改附件名** |
| `backfill.py` | 给缺 `meta.json` 的文献补元数据 | 否 | 否 |
| `tags.py` | 标签改嵌套写法；`autotag` **已弃用** | autotag 花 | **改标签** |

```
python -m tools.curate.sync            定时任务每小时跑的就是这条
python -m tools.curate.junk            列清单（不删）
python -m tools.curate.junk --删除      按清单删
python -m tools.curate.rename <全库json> [apply]
python -m tools.curate.backfill
python -m tools.curate.tags [apply]
```

## 两个刻意的设计（别顺手改掉）

1. **列清单和删除分成两步**。A 组（重复残留）删了不丢东西，
   B 组（库里独一份）**删了就真没了** —— 这两种判断不该由同一条命令替人做完。
2. **`sync` 拉起依赖服务而不只是跳过**（踩坑 #33）。
   之前只「跳过本轮」，Zotero 开机没起来后就一直没人管，
   精读线静默停摆 19 分钟用户才发现。**保活任务就该负责保活。**

## 为什么 `sync` 用子进程跑别的工具

它要跑 `tools.ask.vectorize` 和 `tools.extract.batch`，但
`tools/*` **不许 import 别的 `tools/*`**（REBUILD 第三节硬规则 2）。
子进程按**模块名**拉起：既不构成 import 边，又不怕别人搬家改路径。

## 怎么验证

```
python tools/curate/selftest.py     # 9 条，全离线（分组/改名/标签的判定逻辑）
python -m tools.curate.junk         # 只列清单，不写任何东西
python -m tools.curate.tags         # 不带 apply = 预览
```
