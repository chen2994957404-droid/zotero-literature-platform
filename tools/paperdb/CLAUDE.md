# tools/paperdb · 文献查询库 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。

## 这块是什么

**`structured/*.json` → 一个能查的 SQLite 库**（`data/state/papers.db`）。

它让这类问题第一次可回答：

- 「所有含硼、拉伸强度 > 10 MPa 的体系，按动态键类型分组」
- 「哪些篇有合成条件但没有性能数值」
- 「精层里 `self_healing` 有值的有几篇，粗层呢」

此前答不了的原因很具体：`key_properties` 存的是 `'tensile strength: 12 MPa'`
这种人话，机器比不了大小；而 `compare.md` 是给人竖着看的一张表，不能筛也不能分组。

## 三张表（2026-09-06 由两张扩成三张）

| 表 | 一行是什么 | 关键列 |
|---|---|---|
| `papers` | 一篇文献 | `key` / `title` / `tier` / `source` / `si_used` / `schema_ver` / `is_review` + schema 的每个字段 |
| `samples` | **一个配方** | `key` / `sample_id` / `composition` / `preparation` / `dynamic_bond` / `role` |
| `measurements` | **一个数字** | `key` / `sample_id` / `name` / `raw_name` / `value` / `value_max` / `unit` / `cmp` / `condition` / `location` / `section` / `method` / `raw` |
| `curves` | **一条曲线** | `key` / `fig` / `series` / `chart_type` / `x_label` / `x_unit` / `y_label` / `y_unit` / `n_points` / `confidence` / `caption` / `points` |

`properties` 保留成 `measurements` 的视图（同名同列），**老查询、老 evals、老 SQL 一行都不用改**。
建库时 `_migrate()` 会把 v1 库里那张 `properties` 表丢掉换成视图 —— 库本来就是可再生索引，换掉零风险。

### 为什么要有样品层与出处（这两条是整次改动的全部理由）

**① 最小单元错了。** v1 是「一篇一行」，可一篇论文常有 PBS-1/PBS-2/PBS-3 好几个配方。
数字全挤在一句 `key_properties` 里，拆出来**不知道属于哪个样品** ——
「强度 > 10 MPa 的体系有哪些」只能答出论文，答不出体系。库越大，这个错越致命。

**② 数字没有出处就不敢用。** `tensile strength: 12 MPa` 不告诉你它印在表 2 还是图 3b、
是正文还是 SI、是模型读的文字还是从曲线上抠的。于是每次要引用都得翻回原文。
`measurements(located=True)` 一句话就是「敢引的那些」，`located=False` 是待核清单。

**③ 测试条件是数值的一部分。** 12 MPa 在什么应变速率、什么温度下测的；
自修复 95% 修了几小时。不带条件跨论文比大小，比的是假数。

### 曲线（2026-09-06 加）

源是 `curated/<key>/curves.json`（`tools.digitize` 写的），本模块只把它编进索引。
每条 series 除了原样入 `curves` 表，还由 `schema.curve_measurements()` 派生两条测量：
**Y 的峰值**与**峰值处的 X**，`method='curve'`、出处 `Fig. <n>`、`cmp='~'`
（抠图读数天然是近似值，别装成精确值）。

**只派生峰值**是刻意的：屈服点、模量斜率要看曲线类型与领域惯例，猜错就是往库里灌假数。
曲线原始点一起存着（`points` 列），要更细的分析就取那一列自己算。

### 新旧混住的规矩

`shared.domain.schema.samples_of()` / `iter_measurements()` 是**唯一入口**，
本模块不判断一条记录是 v1 还是 v2：v1 自动合成 `main` 样品、出处留空、
`method='text-v1'`。所以**老数据不用重抽就能进三层**，而且一眼看得出它还没定位。

`parse_property` 依然不换单位。名字则按 `PROPERTY_ALIASES` 归一（`name` 存正名，
`raw_name` 存原文写法）—— 不归一，「强度」这一查就会漏掉一半的库。

## 对外接口

```python
from tools import paperdb

paperdb.rebuild()                       # 三层一起重建 → (篇数, 样品数, 数值条数)
paperdb.query(sql, args)                # 只读 SQL → list[dict]（只接受 SELECT / WITH）
paperdb.find(text='boron', prop='tensile', min_value=10, tier='精层', field='...')
paperdb.stats()                         # 各档次 × 各字段有值率
paperdb.props('tensile')                # 抽到过哪些性能、各多少条、范围多大
paperdb.samples(key=..., text=...)      # 样品层：一行一个配方
paperdb.measurements(prop=..., min_value=..., located=True)   # 测量层：带条件与出处
paperdb.provenance()                    # 多少数字能追溯到原文（体温计）
```

命令行：`--rebuild | --stats | --props X | --find X | --samples | --m X [--located] | --prov | --sql "..."`

## 文件

| 文件 | 干什么 |
|---|---|
| `__init__.py` | 建库 / 只读查询 / 快捷筛法 / 统计 |
| `cli.py` | 人的命令行入口（只解析参数，一行逻辑都没有） |
| `tool.toml` | 工具清单（expose / 花不花钱 / 有什么副作用）—— MCP 服务照它挂 |
| `mcp.py` | 给 agent 的 MCP 面（只做参数转换，不许有逻辑）|
| `README.md` · `SKILL.md` | 给人的说明 · 给 agent 的手册（含**什么时候别用我**）|
| `evals/` | 评测：4 条造出来的记录 + 9 个查询用例，**全离线、默认就跑**。加用例只改 `golden/queries.json` |
| `selftest.py` | 离线自测（不碰真实数据、不调任何服务） |

## 铁律：库是索引，不是真相

真相永远是 `structured/<key>.json`。库删了随时重建（秒级、零成本、不花钱），
所以**本模块只有整库重建，没有增量维护** —— 增量会带来一整类
「库里还留着已删记录」的 bug，而我们什么都换不来。

同理 `query()` 只接受 SELECT / WITH：**要改数据就去改 JSON 再 rebuild**，
不许有第二个真相来源。

**新鲜度是索引自己的事**（R7 窗）：`query()` 每次先比一眼时间戳，
库比最新那份 JSON 旧就自己重建一次（秒级、不花钱）。
此前是「谁写完 JSON 谁负责刷索引」，于是 `tools/extract` 里写着
`from tools import paperdb` —— 违反「工具不许 import 工具」。
真正的毛病不在那行 import，而在**责任放错了地方**：漏一个写入方
（手改过 JSON、从 B 机同步过来一批），用户就查到旧数据，**而且不报错**。

## 什么时候该改这块

- 加/删 schema 字段 → 不用改（列由 `shared.domain.schema.SCHEMA` 自动生成），**但要 rebuild**
- 性能字符串拆得不准 → 改 `shared.domain.schema.parse_property`（纯逻辑，那儿有自测）
- 想加新的筛法 → 加在 `find()` 里；一次性的分析直接用 `query()` 写 SQL
