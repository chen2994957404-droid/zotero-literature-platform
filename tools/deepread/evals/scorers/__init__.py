# -*- coding: utf-8 -*-
"""deepread 的评分器。一个评分器 = 一个「怎么给产出打分」的纯函数。

  - quality.metrics(html)      客观指标：字数 / 图数 / 数值密度 / 章节完整性
  - quality.snapshot_file(p)   同上 + 文件大小与时间
"""
from tools.deepread.evals.scorers.quality import metrics, snapshot_file   # noqa: F401
