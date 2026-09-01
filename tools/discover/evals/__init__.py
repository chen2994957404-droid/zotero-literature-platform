# -*- coding: utf-8 -*-
"""discover 的评测集：**排出来的顺序对不对**（体检只回答「能不能跑」）。

  golden/ranking.json      造出来的候选 + 对照结果 → 应该排成什么样
  scorers/ordering.py      纯函数评分器（判顺序，不判分数）
  thresholds.toml          通过率阈值

跑法：`python -m pytest tools/discover -q`。**全离线、不联网、秒级，默认就跑。**

## 这一组守的是踩坑 #38

「只看跟我的库像不像不够，雪球一开就被高被引通用文献带偏」——
解药写在 `match.rank()` 的默认权重里：相关度 0.6 压过被引 0.25，被引还开了方压缩。

**不把它钉住的话**，以后有人觉得「被引权重是不是太低了」顺手一调，
找文献就退化成「按被引排序」—— 那用 Google Scholar 就行，不需要这个平台。
而且这种退化**不会报错**，只会让结果慢慢变得没用。

## 还缺的那一半（要主力机的数据）

真正的召回质量该拿**天然金标**验：用户后来实际导入了哪几篇。
那份数据只有主力机上有（A 机是测试账号）。现在这套只验排序规则本身。
"""
import json
import os
import tomllib

_HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_HERE, 'thresholds.toml'), 'rb') as _f:
    THRESHOLDS = tomllib.load(_f)

MIN_PASS_RATE = THRESHOLDS['thresholds']['min_pass_rate']


def golden():
    with open(os.path.join(_HERE, 'golden', 'ranking.json'), encoding='utf-8') as f:
        return json.load(f)
