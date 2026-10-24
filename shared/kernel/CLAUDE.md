# kernel · 内核环 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。

## 这个文件夹是什么

**四环架构最底下的一环。谁都可以依赖它，它不依赖任何人。**

规则只有一条，但必须绝对遵守：

> `shared/kernel/` 里的代码**不许 import** `shared.domain` / `shared.adapters` / `tools` / `host`，
> 不许联网，不许 import 第三方库（只用 Python 标准库；`keyring` 是唯一例外，在 config 里延迟 import）。

违反了 `pytest` 会立刻变红（`tests/test_architecture.py::test_依赖方向不许反向`）。

为什么这么严：core 是所有东西的地基。地基一旦反过来依赖上层，
整张依赖网就不再「绝对有序」，改任何一处都可能波及全局 ——
那正是 2026-08 那次重构要根治的病（见 `docs/explain/架构重构_v2总体设计.md`）。

## 现有成员

| 文件 | 是什么 |
|---|---|
| `paths.py` | **数据契约的唯一实现**。全系统只有它知道 `data/` 五层里的目录长什么样 |
| `catalog.py` | 证据库目录：「有没有这篇」的唯一入口（读 `curated/<id>/meta.json`，零网络）|
| `config/` | 密钥与本机设置：环境变量 → 系统凭据库 → `.env` |
| `log.py` | 统一日志：像 print 一样调用，带时间戳、落盘、自动轮转（5MB × 3 份）|
| `errors.py` | 异常分类。分类维度是**「该拿它怎么办」**，不是「哪里出的错」|
| `jobs.py` | **处理记录**（SQLite）：哪篇做到哪一步、失败在哪 —— 面板的「落地处理进度」就读它 |
| `heartbeat.py` | 常驻服务 / 批量作业的心跳：卡住了要有人知道 |
| `role.py` | 机器角色（dev / test / prod）：这台机器允许做什么 |
| `cli/` · `subproc/` | 命令行取参 · 不弹窗的子进程调用 |

## jobs.py 怎么用

```python
from shared.kernel import jobs

with jobs.track(key, 'parse') as run:
    do_the_work()

jobs.last(key, 'parse')        # 最后一次执行（含 error）
jobs.summary()                 # 按步骤统计，给面板显示进度
```

两条设计约定，改它之前必须先认同：

1. **状态库是索引，不是真相。**真相永远是硬盘上的产物文件。
   所以 `is_done()` 还要 `require=` 产物名；库删了能重建，产物没了才是真丢数据。
   也因此：状态库里没记录但产物在（上线前做的老数据），一律**认它**，不重跑全库。
2. **它坏了不许拖垮主流程。**所有读写都兜底，失败只打一行日志。
   记不上账可以，正在跑的解析白做不行。

## log.py 怎么用

```python
from shared.kernel.log import get_logger
log = get_logger('ingest')

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

paths.local_pdf(key)      # raw/<id>/main.pdf          ← 原件，丢了只能重下
paths.find_local_si(key)  # raw/<id>/si.*（没有返回 ''）
paths.fulltext(key)       # raw/<id>/parsed/full.md    ← 解析结果，可重跑 MineRU
paths.si_fulltext(key)    # raw/<id>/si_parsed/full.md
paths.meta(key)           # curated/<id>/meta.json     ← 目录卡
paths.VECTOR_DB / paths.LOGS / paths.CURATED / paths.RAW   # 目录常量
paths.log('ingest')       # logs/ingest.log
paths.paper_id_from_doi('10.1021/acs.x')   # → doi_10.1021-acs.x
paths.check_key(k)        # 校验文献 id，不合法就抛错
```

### 两条设计约定

1. **不做 I/O**，除非显式传 `create=True`。「算一下路径」不该在硬盘上留下痕迹。
2. **返回绝对路径字符串**（不是 Path 对象），与项目现有风格一致，可直接喂 `open` / subprocess。

## 加新路径时

在 `paths.py` 里加一个函数 + 在 `shared/kernel/tests/` 里加一条断言。
**那条断言就是数据契约本身** —— 以后谁改了目录布局而忘了同步文档，测试会红。

## 绝对不要做的事

- 不要在别的地方拼 `data/` 的路径。守卫会拦。
- 不要让 kernel 依赖 `shared/domain`、`shared/adapters`、`tools/` 或 `host/`。它是最底层，谁都依赖它、它不依赖任何人。
