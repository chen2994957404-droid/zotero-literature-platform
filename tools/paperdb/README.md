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
python -m tools.paperdb --sql "SELECT tier, COUNT(*) n FROM papers GROUP BY tier"
```

Python：

```python
from tools import paperdb
paperdb.find(text='boron', prop='tensile', min_value=10, tier='精层')
paperdb.query('SELECT ...')      # 只接受 SELECT / WITH
```

## 两张表

| 表 | 一行是什么 |
|---|---|
| `papers` | 一篇文献：key / title / tier / source / si_used / schema 的每个字段 |
| `properties` | 一条性能数值：name / value / value_max / unit / cmp / raw |

`'Mn: 3.2×10^4 g/mol'` 会被拆成 `name='mn', value=32000.0, unit='g/mol'`。
拆不出数字的照样入库，只是不能参与大小比较。

## 铁律：库是索引，不是真相

真相永远是 `structured/<key>.json`。库删了随时重建（秒级、零成本），
所以**只有整库重建，没有增量维护**；`query()` 也只接受 SELECT / WITH ——
要改数据就去改 JSON 再 rebuild，不许有第二个真相来源。

**不做单位换算**：MPa 与 kPa 混在一起时宁可让人看见。查询时按「名字 + 单位」一起筛。
