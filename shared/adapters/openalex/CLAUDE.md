# openalex · OpenAlex 检索适配层 —— 给 LLM 的说明

## 是什么

OpenAlex 学术检索 API 的唯一入口（免费、无需密钥）。**属于 adapters 环**。

## 为什么存在

重构前同一个 API 被**三处各实现了一遍**：

| 处 | 状况 |
|---|---|
| `adapters/snowball` | 有退避重试、礼貌 UA、字段裁剪 —— 实现最好 |
| `tools/discover`（旧 paper_discovery）| 裸 urlopen，无重试 |
| `找新文献/find_papers.py` | 裸 urlopen，无重试，又抄了一遍摘要还原 |

后果一：OpenAlex 一限流，snowball 会退避重试，另外两个直接失败。
后果二（更隐蔽）：**字段名各叫各的**，于是 `paper_discovery` 发 `cited_by`、
`discover.py` 读 `cited`，两边都不是 `citations` 也互相对不上 ——
走 OpenAlex 检索时引用数**永远是 0**，还连累了按被引排序的打分。
三份实现各写各的，必然长成这样。

## 接口

```python
from adapters import openalex
items, total = openalex.search('polyborosiloxane', limit=25, year_from=2015)
w = openalex.work_by_doi('10.1021/xxx')     # 查不到返回 None
openalex.restore_abstract(inv)              # 倒排索引摘要 → 正常文本
openalex.normalize(work)                    # OpenAlex work → 统一文献字典
```

## 统一文献字典（与 adapters.sciverse 同构）

```
title · doi · year · venue · citations · abstract · is_oa · oa_url
openalex_id · first_author
```

⚠ **引用数字段名是 `citations`**，不是 `cited` 也不是 `cited_by`。

## 行为

- 429 / 5xx 自动退避重试（批量跑时必然撞上限流）
- 失败抛 `core.errors` 分类异常：限流 → `RateLimited`，其余 → `ExternalServiceError`
- 摘要用倒排索引存储（OpenAlex 为规避版权的历史设计），必须还原才能用 ——
  而摘要正是判断「跟我的方向相不相关」的主要依据

## 验证

```
python adapters/openalex/selftest.py     # 前半段离线，后半段真调一次 API
```
