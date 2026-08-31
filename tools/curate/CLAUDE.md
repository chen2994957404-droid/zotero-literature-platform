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
| ~~`sync.py`~~ | R7 窗搬去 `host/autosync/`（它驱动别的工具，不是维护库房）| — | 否 |
| `junk.py` | 找出无 PDF 的残留条目 → 确认后删 | 否 | **删条目** |
| `rename.py` | 附件统一命名（正文 / SI / 快照）| 否 | **改附件名** |
| `backfill.py` | 给缺 `meta.json` 的文献补元数据 | 否 | 否 |
| `tags.py` | 标签改嵌套写法；`autotag` **已弃用** | autotag 花 | **改标签** |

```
python -m tools.curate.junk            列清单（不删）
python -m tools.curate.junk --删除      按清单删
python -m tools.curate.rename <全库json> [apply]
python -m tools.curate.backfill
python -m tools.curate.tags [apply]
```

## 两个刻意的设计（别顺手改掉）

1. **列清单和删除分成两步**。A 组（重复残留）删了不丢东西，
   B 组（库里独一份）**删了就真没了** —— 这两种判断不该由同一条命令替人做完。
2. **打标签/改名一律先预览再 apply**，不带参数就是预览。
   写真实 Zotero 库的操作不可逆，用户又不懂编程 —— 让他先看见要改什么。

## 定时同步不在这里了（R7 窗搬走）

「新文献自动入库」那条每小时的定时作业住在 **`host/autosync/`**。
它做的两件事都是**驱动别的工具**（`tools.ask.vectorize` 与 `tools.extract`），
还顺手把睡着的 Zotero / Ollama 任务唤醒 —— 那是平台的活，不是库房维护。
它此前没被「工具不许 import 工具」守卫抓到，只因为走的是子进程：
**那是形式上的规避，不是本质上的合规。**

## 怎么验证

```
python tools/curate/selftest.py     # 9 条，全离线（分组/改名/标签的判定逻辑）
python -m tools.curate.junk         # 只列清单，不写任何东西
python -m tools.curate.tags         # 不带 apply = 预览
```

## 五件套（R4 窗补，2026-08-31）

| 文件 | 干什么 |
|---|---|
| `tool.toml` | 工具清单：`expose` / 花不花钱 / 有什么副作用 / 要哪档机器角色 |
| `cli.py` | 人的命令行入口（`python -m tools.curate`），只解析参数 |
| `mcp.py` | 给 agent 的 MCP 面（**只做参数转换，不许有逻辑**）|
| `README.md` | 给人：这是什么、怎么用 |
| `SKILL.md` | 给 agent：什么时候用我、怎么用、**什么时候别用我** |
| `prompts/` | 系统提示词（`<名>_v<N>.txt`）。**只增不改**：改措辞就新建下一版，旧版留着 |
| `evals/` | 评测：金标 / 评分器 / 阈值。R5 窗建的骨架，**还是空的**，别当成已经验过 |

本工具在 MCP 上是 **prompt**（花钱/有副作用 → 由人在客户端里点，模型不能自己调）。
判据与守卫见 `host/mcp/CLAUDE.md`。
