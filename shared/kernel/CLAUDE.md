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
那正是这次重构要根治的病（见 `docs/explain/架构重构_v2总体设计.md`）。

## 现有成员

| 文件 | 是什么 |
|---|---|
| `paths.py` | **数据契约的唯一实现**。全系统只有它知道 `data/` 五层里的目录长什么样 |
| `log.py` | 统一日志：像 print 一样调用，带时间戳、落盘、自动轮转（5MB × 3 份）|
| `errors.py` | 异常分类。分类维度是**「该拿它怎么办」**，不是「哪里出的错」|
| `jobs.py` | **任务状态库**（SQLite）：谁做到哪一步、谁产的、失败在哪、该重跑谁 |
| `prompts/` | **提示词的唯一读取口**。提示词是数据不是代码，住在 `<工具>/prompts/<名>_v<N>.txt`，**只增不改** |

## jobs.py 怎么用

```python
from shared.kernel import jobs

if jobs.is_done(key, 'main_summary', require='summary', prompt_ver=2):
    ...跳过，省一次 MineRU + DeepSeek 的钱...

with jobs.track(key, 'main_summary', model=MODEL, prompt_ver=2) as run:
    do_the_work()
    run.note(cost=0.12)        # 做完才知道的东西，补记进去

jobs.last(key, 'main_summary')             # 最后一次执行（含 producer/model/error）
jobs.stale('main_summary', prompt_ver=3)   # 提示词升到 v3 后，谁该重跑
jobs.summary()                             # 按步骤统计，给面板显示进度
```

两条设计约定，改它之前必须先认同：

1. **状态库是索引，不是真相。**真相永远是硬盘上的产物文件。
   所以 `is_done()` 还要 `require=` 产物名；库删了能重建，产物没了才是真丢数据。
   也因此：状态库里没记录但产物在（上线前做的老数据），一律**认它**，不重跑全库。
2. **它坏了不许拖垮主流程。**所有读写都兜底，失败只打一行日志。
   记不上账可以，正在跑的精读白做不行。

## log.py 怎么用

```python
from shared.kernel.log import get_logger
log = get_logger('zotero_watcher')

log('开始处理', key)        # 像 print 一样用（老代码零成本迁移）
log.warn('PDF 找不到')
log.error('MineRU 失败')
log.path                    # 写到哪个文件（面板展示日志时用）
```

**不要再自己写 `def log(msg)`，也绝不要劫持内置 `print`。**
改造前这三种写法各存在一份，且都不会轮转 —— 常驻服务的日志只会一直长下去。

⚠ 坑（踩坑 #48）：`logging.getLogger(名)` 是**进程级全局单例**。
判断「要不要挂 handler」不能只看「有没有」，要看「指向的是不是同一个文件」——
否则要么日志写两遍，要么换了目录不生效。

## errors.py 怎么用

```python
from shared.kernel import errors

raise errors.ConfigError('MINERU_TOKEN 没配，去控制面板填')
raise errors.RateLimited('MineRU 限流', service='mineru', retry_after=30)

if errors.is_retryable(e):   ...退避重试...
else:                        ...记下来，跳过...
```

分类维度是**「该拿它怎么办」**：`BadInputError` / `ConfigError` / `DataError` /
`AuthError` 都不该重试；只有 `ExternalServiceError` 系列可以。
不认识的异常一律不重试 —— 宁可让失败暴露，也不要对着永远不会成功的调用烧钱。

## paths.py 怎么用

```python
from shared.kernel import paths

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

- 不要在别的地方拼 `data/` 的路径。守卫会拦。
- 不要让 kernel 依赖 `shared/domain`、`shared/adapters`、`tools/` 或 `host/`。它是最底层，谁都依赖它、它不依赖任何人。
