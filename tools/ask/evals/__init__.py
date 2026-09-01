# -*- coding: utf-8 -*-
"""ask 的评测集：**答案带不带得出出处**。

  scorers/traceability.py  纯函数评分器（只看结构，不看模型说了什么）
  thresholds.toml          通过率阈值

跑法：`python -m pytest tools/ask -q`。**全离线、不调模型、秒级，默认就跑。**

## 验什么，不验什么

**不验答案质量** —— 那要有「已知答案在哪一篇」的问题，还要真调模型花钱，
而问题和标准答案都得用户来出（他才知道自己库里哪篇讲了什么）。

**验的是可追溯性的结构**，也就是这个工具的全部卖点：
  · 每一段材料进上下文时都带着出处标记 —— 模型才可能引对
  · 来源列表**不多不少**：多了会让用户去翻一篇根本没参与作答的文献，
    少了他就不知道这句话是从哪来的
  · **没有证据时不硬答** —— 宁可说「没找到」，也不要拿跑题片段编一段出来

为什么只看结构不看模型输出：模型每次说的都不一样，拿它当金标的话
评测会随机变红，而**随机变红的评测等于没有评测**。
"""
import os
import tomllib

_HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_HERE, 'thresholds.toml'), 'rb') as _f:
    THRESHOLDS = tomllib.load(_f)

MIN_PASS_RATE = THRESHOLDS['thresholds']['min_pass_rate']
