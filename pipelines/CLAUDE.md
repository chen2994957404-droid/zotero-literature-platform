# pipelines · 编排环 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。

## 判据：什么东西该放这里

**本身不解决任何原子问题，只负责「按什么顺序调用谁」的代码。**
也就是宪法里的「定理」—— 由公理组合而成的能力。

宪法铁律 1 给了判据的反面：
> 「如果一个能力还能被拆成『先做 A 再做 B』，它就不是公理，是定理。」

## 现有成员（阶段 2 从公理层迁进来的四块）

它们此前混在 `modules/` 里被当成公理，但都不满足公理的定义 —— 都是组合：

| 块 | 组合了什么 |
|---|---|
| `chart_digitize` | 图 → LLM 读图 → 数据点（宪法明确说过它是「独立定理」）|
| `query_expand` | 问题 → LLM → 多个检索式 |
| `paper_discovery` | `adapters.openalex` 检索 + 库内匹配标记 |
| `lib_match` | `adapters.vectordb` 检索 + 排序判定 |
| `deepread` | **阶段 3 搬进来的主线**：解析 + 正文精读 + SI + 合并（见它自己的 CLAUDE.md）|
| `extract` | 结构化抽取：full.md → 对齐字段 → 并入横向对比表（字段定义在 `domain/schema`）|
| `paper_db` | 结构化记录 → 可查询的 SQLite 库（性能数值拆成能比大小的数）|

## 依赖规矩

可以 import：`core`、`domain`、`adapters`、以及别的 pipeline。
不许 import：`apps`（界面层）。

**不许直接联网。** 要调外部服务，先把它包成 `adapters/<服务名>`，本环只调那块。
守卫会拦（`python -m pytest`）—— 重构前 `paper_discovery` 正是反面教材：
编排层里直接写着 OpenAlex 的 URL 和 `urlopen`。

## 阶段 3 做到哪了（2026-08-27）

**精读线已经搬进来了**（`pipelines/deepread`）：watcher 里那五个
「脚本路径 + 参数顺序」的子进程调用，变成了一次 `deepread.run(key, ...)`。
配套上线了 `core/jobs`（SQLite 状态库）：每一步谁产的、哪个模型、哪版提示词、
失败原因都记账，于是「只补缺的部分」「提示词升级即重跑清单」变成一句查询。

`文献精读/` 下的 `deepread_v4.py` / `si_deepread.py` / `merge_summary.py`
现在只是**命令行薄壳**，逻辑都在这儿 —— 老的 .bat 和批量脚本一行没改照常能用。

**结构化抽取也搬进来了**（`pipelines/extract` + `domain/schema`），
**Zotero 写操作收进了 `adapters/zotero_client`** ——
至此 `zotero_watcher.process_item` **不再拉任何子进程**，
而且全项目只有一个文件会碰 api.zotero.org（机器角色守卫因此只需一处）。

还没搬的（下一步）：

- **向量化 / 问答**：`库内问答/` 三个脚本（依赖 Ollama，只能在主力机实测）
- **控制面板接真进度**：状态库已有数据（`jobs.summary()`），面板还在看日志尾巴
- watcher 还能再瘦：把「轮询 → 入队」与「处理一篇」分开（设计文档阶段 4 第 19 项）
