# core · 内核环 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。

## 这个文件夹是什么

**四环架构最底下的一环。谁都可以依赖它，它不依赖任何人。**

规则只有一条，但必须绝对遵守：

> `core/` 里的代码**不许 import** `domain` / `adapters` / `pipelines` / `apps`，
> 不许联网，不许 import 第三方库（只用 Python 标准库）。

违反了 `pytest` 会立刻变红（`tests/test_architecture.py::test_依赖方向不许反向`）。

为什么这么严：core 是所有东西的地基。地基一旦反过来依赖上层，
整张依赖网就不再「绝对有序」，改任何一处都可能波及全局 ——
那正是这次重构要根治的病（见 `docs/架构重构_v2总体设计.md`）。

## 现有成员

| 文件 | 是什么 |
|---|---|
| `paths.py` | **数据契约的唯一实现**。全系统只有它知道 `workflow_data` 里的目录长什么样 |

规划中（尚未建）：`log.py`（统一日志）、`errors.py`（异常分类）、
`jobs.py`（SQLite 任务状态库，支撑续跑/重试/只补缺的）。见设计文档第三节。

## paths.py 怎么用

```python
from core import paths

paths.fulltext(key)       # library/<key>/parsed/full.md   ← 不可再生的核心资产
paths.layout(key)         # library/<key>/parsed/layout.json
paths.summary(key)        # library/<key>/summary.html
paths.si_summary(key)     # library/<key>/si_summary.html
paths.summary_full(key)   # library/<key>/summary_full.html
paths.meta(key)           # library/<key>/meta.json
paths.structured(key)     # structured/<key>.json
paths.compare('compare_PBS')  # structured/compare_PBS.md

paths.LIBRARY / paths.STRUCTURED / paths.VECTOR_DB / paths.LOGS   # 目录常量
paths.log('zotero_watcher')          # logs/zotero_watcher.log
paths.runtime('watcher_heartbeat.txt')

paths.all_keys()                     # 库里所有已归档文献的 key
paths.has(key, 'summary')            # 这篇的精读在不在
paths.check_key(k)                   # 校验 8 位 item key，不合法就抛 BadKeyError
```

### 两条设计约定

1. **不做 I/O**，除非显式传 `create=True`。「算一下路径」不该在硬盘上留下痕迹。
2. **返回绝对路径字符串**（不是 Path 对象），与项目现有风格一致，可直接喂 `open` / subprocess。

## 加新路径时

在 `paths.py` 里加一个函数 + 在 `tests/test_core_paths.py` 里加一条断言。
**那条断言就是数据契约本身** —— 以后谁改了目录布局而忘了同步文档，测试会红。

## 绝对不要做的事

- 不要在别的地方写 `os.path.join(ROOT, 'workflow_data', ...)`。守卫会拦。
- 不要让 core 依赖 `modules/`。现在还没有这种依赖，别开这个头。
