# tools/paperdb · 文献查询库

**一句话**：把 `structured/*.json` 建成一个能筛、能分组、能比大小的 SQLite 库。

它让这类问题第一次可回答：

- 所有含硼、拉伸强度 > 10 MPa 的体系，按动态键类型分组
- 哪些篇有合成条件但没有性能数值
- 精层里 `self_healing` 有值的有几篇，粗层呢

## 怎么用

```
python -m tools.paperdb --rebuild                 # 从 structured/*.json 重建（秒级、不花钱）
python -m tools.paperdb --stats                   # 各档次 × 各字段有值率
python -m tools.paperdb --props tensile           # 抽到过哪些性能、范围多大
python -m tools.paperdb --find boron --prop tensile --min 10
python -m tools.paperdb --samples                 # 样品层：一行一个配方
python -m tools.paperdb --m tensile --min 10 --located   # 测量层：能追溯到原文的数字
python -m tools.paperdb --curves                  # 曲线层：抠过哪些图
python -m tools.paperdb --journals               # 库里的文献发在什么档次的刊上
python -m tools.paperdb --find 硼 --journal 顶刊  # 只看顶刊的那些
python -m tools.paperdb --prov                    # 有多少数字能追溯（体温计）
python -m tools.paperdb --sql "SELECT tier, COUNT(*) n FROM papers GROUP BY tier"
```

Python：

```python
from tools import paperdb
paperdb.find(text='boron', prop='tensile', min_value=10, tier='精层')
paperdb.samples(key='ABCD1234')                 # 这篇有几个配方
paperdb.measurements(prop='tensile strength', min_value=10, located=True)
paperdb.provenance()                            # 数字有多少能追溯到原文
paperdb.curves(key='ABCD1234')                  # 这篇抠过哪些曲线
paperdb.curve_points('ABCD1234', 3)             # 第 3 张图的原始点
paperdb.query('SELECT ...')      # 只接受 SELECT / WITH
```

## 三张表（一篇 → 若干样品 → 若干数字）

| 表 | 一行是什么 |
|---|---|
| `papers` | 一篇文献：key / title / tier / source / si_used / schema 的每个字段 |
| `samples` | **一个配方**：sample_id / 组成 / 制备 / 动态键 / 它在这篇里的角色 |
| `measurements` | **一个数字**：name / value / unit / 测试条件 / **出处** / 正文还是 SI / 谁抽的 |
| `papers` 的期刊列 | `journal` / `issn` / `journal_tier` / `publisher` —— 来自 `tools/curate journals` |
| `curves` | **一条曲线**：哪篇第几张图、图例名、轴与单位、多少个点、原始点、读得多确信 |

（`properties` 还在，是 `measurements` 的兼容视图，老查询照跑。）

**为什么要分到样品这一层**：一篇论文常有 PBS-1 / PBS-2 / PBS-3 好几个配方，
各有各的强度。全挤进一句 `key_properties`，拆出来的数字**不知道是哪个样品的** ——
「强度 > 10 MPa 的体系有哪些」答出来的就只能是论文，不是体系。

**为什么每个数字要带出处**：没有「表 2 / 图 3b / SI」这一栏，
数字就不敢写进论文，还得自己翻回原文。`--m ... --located` 一句话拉出「敢引的那些」，
`--unlocated` 拉出「还得自己核的那些」。

`'Mn: 3.2×10^4 g/mol'` 会被拆成 `name='mn', value=32000.0, unit='g/mol'`。
拆不出数字的照样入库，只是不能参与大小比较。
性能名字按统一词表归一（`ultimate tensile stress` → `tensile strength`），
**只归一名字，绝不换算单位**。

**从图上抠下来的数也在同一张测量表里**（`method='curve'`，出处写成 `Fig. 3`）：
每条曲线派生「峰值」和「峰值处的 X」两条。曲线本身连原始点一起留着，
随时能取出来画图 —— 图只需花钱读一次。

**v1 老记录不用重抽也能进三层**：自动合成一个 `main` 样品，出处留空 ——
空出处本身就是信息，它精确地说「这个数字还没定位到原文」。

## 铁律：库是索引，不是真相

真相永远是 `structured/<key>.json`。库删了随时重建（秒级、零成本），
所以**只有整库重建，没有增量维护**；`query()` 也只接受 SELECT / WITH ——
要改数据就去改 JSON 再 rebuild，不许有第二个真相来源。

**不做单位换算**：MPa 与 kPa 混在一起时宁可让人看见。查询时按「名字 + 单位」一起筛。
