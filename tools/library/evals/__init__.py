# -*- coding: utf-8 -*-
"""library 的评测集：**检索返回的条目对不对**（体检只回答「能不能跑」）。

## 为什么这一套是 `live` 的

`paperdb` 的评测能全离线，因为它的输入（`structured/*.json`）可以造。
`library` 不行 —— 它要回答的是「**在用户真实的 Zotero 库里**，搜一个词能不能
把该出来的搜出来」。拿造出来的假库测，测的是 `urllib` 通不通，不是检索质量。

所以这套金标标了 `@pytest.mark.live`：**默认不跑**，在开着 Zotero 的机器上
`python -m pytest tools/library -m live` 单独跑。免费、只读、几秒钟。

## 金标为什么不写死具体的条目

写死「搜 XX 应该返回 ABCD1234」的话，用户删一篇、改个标题，评测就红了 ——
而那种红不代表出问题。**评测红了却不代表出问题，是评测失效的第一步。**

这里改成验**不变量**：从库里随便取一篇，用它自己的标题去搜，必须搜得到它。
这条对任何库、任何时候都成立，且真的能抓到问题（分词坏了、qmode 传错了、
编码坏了、分页参数写反了，都会让它挂）。
"""
import os
import tomllib

_HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_HERE, 'thresholds.toml'), 'rb') as _f:
    THRESHOLDS = tomllib.load(_f)

SAMPLE_N = THRESHOLDS['thresholds']['sample_items']
MIN_PASS_RATE = THRESHOLDS['thresholds']['min_pass_rate']
