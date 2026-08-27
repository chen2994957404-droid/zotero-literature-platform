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

## 依赖规矩

可以 import：`core`、`domain`、`adapters`、以及别的 pipeline。
不许 import：`apps`（界面层）。

**不许直接联网。** 要调外部服务，先把它包成 `adapters/<服务名>`，本环只调那块。
守卫会拦（`python -m pytest`）—— 重构前 `paper_discovery` 正是反面教材：
编排层里直接写着 OpenAlex 的 URL 和 `urlopen`。

## 还没做的（阶段 3，收益最大的一步）

平台的主线工作流 —— 精读、SI 精读、合并、结构化抽取、向量化、问答 ——
**现在还是靠 subprocess 互相拉起来的独立脚本**：

```python
subprocess.run([sys.executable, ROOT/'数据抽取'/'extract_structured.py', key])
```

接口就是「文件路径 + 参数顺序」。改个文件夹名、调个参数次序，运行时才炸。
而且没有类型、没有状态、失败了不能续跑、面板看不到进度。

阶段 3 要把它们变成这里的函数（`run(key, ctx) -> Result`，由 step 组成、幂等、
可续跑），并配一个 `core/jobs` 的 SQLite 状态库支撑「只补缺的部分」。
详见 `docs/架构重构_v2总体设计.md` 第三节 A 与第六节。
