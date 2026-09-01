# -*- coding: utf-8 -*-
"""paperdb 的评测集：**查询返回的东西对不对**（体检只回答「能不能跑」）。

  golden/queries.json     造出来的记录 + 一组查询与期望结果
  scorers/query_match.py  纯函数评分器（集合比对，不判顺序）
  thresholds.toml         通过率阈值的唯一出处

跑法：`python -m pytest tools/paperdb -q`（`tests/test_evals.py` 里）。
**全离线、不花钱、秒级**，所以它默认就跑，不用记得另外跑一遍。

加一条金标 = 往 `queries.json` 的 `cases` 里加一项，不用改任何 .py。
每条都要写 `why`：**说不清为什么要验它，就说明这条不值得验。**
"""
import json
import os
import tomllib

_HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_HERE, 'thresholds.toml'), 'rb') as _f:
    THRESHOLDS = tomllib.load(_f)

MIN_PASS_RATE = THRESHOLDS['thresholds']['min_pass_rate']


def golden():
    """读金标：{records, cases}。"""
    with open(os.path.join(_HERE, 'golden', 'queries.json'), encoding='utf-8') as f:
        g = json.load(f)
    return g['records'], g['cases']
