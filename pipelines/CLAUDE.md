# pipelines · 搬家途中的临时住户 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。

## ⚠ 这个文件夹正在消失

重构后的组织原则是**按工具切片**：一个工具 = 一个自包含的包，住在 `tools/`
（代码、MCP 暴露、skill、提示词、评测、测试、文档全在一个文件夹里）。

`pipelines/` 是搬家途中的中转站。**别往这里加新东西** ——
新能力直接建 `tools/<name>/`。施工手册见根目录 `REBUILD.md`。

## 还剩谁，各自要去哪（R3 窗）

| 块 | 组合了什么 | 要搬去 |
|---|---|---|
| `query_expand` | 问题 → LLM → 多个检索式 | `tools/ask` |
| `lib_match` | `adapters.vectordb` 检索 + 排序判定 | `tools/ask` |
| `paper_discovery` | `adapters.openalex` 检索 + 库内匹配标记 | `tools/discover` |
| `direction_map` | 方向地图 / 选题 | `tools/direction` |

## R2 窗（2026-08-30）已经搬走的

| 原来 | 现在 |
|---|---|
| `pipelines/deepread` + `文献精读/`（12 个脚本） | `tools/deepread/` |
| `pipelines/extract` + `数据抽取/`（6 个脚本） | `tools/extract/` |
| `pipelines/paper_db` + `数据抽取/查询库.py` | `tools/paperdb/` |
| `pipelines/chart_digitize` | `tools/digitize/` |

## 依赖规矩（搬走之前照旧）

可以 import：`shared.kernel`、`shared.domain`、`shared.adapters`。
**不许直接联网** —— 要调外部服务，先包成 `shared/adapters/<服务名>`，本环只调那块。
守卫会拦（`python -m pytest`）。反面教材：重构前 `paper_discovery` 的编排层里
直接写着 OpenAlex 的 URL 和 `urlopen`。

搬进 `tools/` 之后还多一条：**`tools/*` 不许 import 别的 `tools/*`**，
要共用就下沉到 `shared/`，门槛是「被 ≥2 个工具用到」。
