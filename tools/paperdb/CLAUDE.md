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

## 两张表

| 表 | 一行是什么 | 关键列 |
|---|---|---|
| `papers` | 一篇文献 | `key` / `title` / `tier` / `source` / `si_used` / `schema_ver` / `is_review` + schema 的每个字段 |
| `properties` | 一条性能数值 | `key` / `name` / `value` / `value_max` / `unit` / `cmp` / `raw` |

`properties` 由 `shared.domain.schema.parse_properties()` 拆出来：
`'Mn: 3.2×10^4 g/mol'` → `name='mn', value=32000.0, unit='g/mol'`；
`'225–300 °C'` → `value=225, value_max=300`；`'>20 times'` → `cmp='>'`。
拆不出数字的照样入库（`value` 为 NULL），只是不能参与大小比较。

**不做单位换算**：MPa 与 kPa 混在一起时宁可让人看见 —— 偷偷换算错，
比查不到更难发现。查询时按「名字 + 单位」一起筛（`find(prop=..., unit=...)`）。

## 对外接口

```python
from tools import paperdb

paperdb.rebuild()                       # 从 structured/*.json 整库重建
paperdb.query(sql, args)                # 只读 SQL → list[dict]（只接受 SELECT / WITH）
paperdb.find(text='boron', prop='tensile', min_value=10, tier='精层', field='...')
paperdb.stats()                         # 各档次 × 各字段有值率
paperdb.props('tensile')                # 抽到过哪些性能、各多少条、范围多大
```

命令行：`python -m tools.paperdb --rebuild | --stats | --props X | --find X | --sql "..."`

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
