# -*- coding: utf-8 -*-
"""extract 的评测集：抽出来的东西**被理解得对不对**。

  golden/records.json    造出来的记录 → 应该被怎么理解
  scorers/records.py     纯函数评分器
  thresholds.toml        通过率阈值

跑法：`python -m pytest tools/extract -q`。**全离线、不花钱、秒级，默认就跑。**

## 这一组验什么，不验什么

**不验**「模型抽得准不准」—— 那要拿几篇**人工核对过**的真实
`structured/<KEY>.json` 当金标，而人工核对得用户来做，比对还要花钱重抽一遍。
天然的金标其实存在（用户核对过的那几篇），只是在主力机上。

**验的是**抽完之后那一整套确定性的理解：
是不是综述、属于哪一档、哪些字段算「有值」、性能字符串怎么拆成能比大小的数。

为什么这一半也很值得验：**对比表和查询库的正确性全建在它们上面**。
档次判错，用户就分不清空格是「这篇本来就没有」还是「粗层没抽到」——
对比表的价值当场归零（那正是 2026-08-28 加档次标记的原因）。
有值率判错，「要不要花钱重抽」这个决定就建在假数上。

加金标 = 往 `records.json` 里加一项，不用改任何 .py。每条都要写 `why`。
"""
import json
import os
import tomllib

_HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_HERE, 'thresholds.toml'), 'rb') as _f:
    THRESHOLDS = tomllib.load(_f)

MIN_PASS_RATE = THRESHOLDS['thresholds']['min_pass_rate']


def golden():
    with open(os.path.join(_HERE, 'golden', 'records.json'), encoding='utf-8') as f:
        return json.load(f)
