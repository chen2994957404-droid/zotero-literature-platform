# -*- coding: utf-8 -*-
"""direction 的评测集：**该聚到一起的有没有聚到一起**。

  golden/clusters.json     答案由构造保证的引文图 + 趋势判定
  scorers/grouping.py      纯函数评分器（比对集合的集合，不判簇的编号）
  thresholds.toml          通过率阈值

跑法：`python -m pytest tools/direction -q`。**全离线、不联网、秒级，默认就跑。**

## 金标怎么来的：不靠人工标注，靠构造

README 原来写的填法是「一条已知窄带，人工标出这几篇应该是一簇」——
那要用户花时间标，标完还只覆盖那一条窄带。

换了个办法：**把图造出来，让正确答案成为构造的一部分**。
A 簇三篇共享 RA*，B 簇三篇共享 RB*，两簇之间零重叠 ——
任何还算合格的社区发现都必须把它们分开，分不开就是真的坏了。

## 还缺的那一半

这样验的是「算法有没有被改坏」，**不是「在真实数据上效果好不好」**。
后者仍然要真实窄带 + 人的判断（「这两篇确实是一支吗」），
而且那份判断只有用户做得了。
"""
import json
import os
import tomllib

_HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_HERE, 'thresholds.toml'), 'rb') as _f:
    THRESHOLDS = tomllib.load(_f)

MIN_PASS_RATE = THRESHOLDS['thresholds']['min_pass_rate']


def golden():
    with open(os.path.join(_HERE, 'golden', 'clusters.json'), encoding='utf-8') as f:
        return json.load(f)
