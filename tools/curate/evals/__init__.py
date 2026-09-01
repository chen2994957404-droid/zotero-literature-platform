# -*- coding: utf-8 -*-
"""curate 的评测集：**它做的判断对不对**（体检只回答「能不能跑」）。

  golden/decisions.json   四组「输入 → 应该做出的判断」，全是造出来的输入
  scorers/decisions.py    纯函数评分器
  thresholds.toml         通过率阈值（1.0，理由写在里面）

跑法：`python -m pytest tools/curate -q`。**全离线、不碰真实库、秒级，默认就跑。**

## 为什么这块的评测优先级高

它写用户**真实的 Zotero 库**，而且都是不可逆的：改附件名、删条目、改标签。
别的工具判错了大不了重跑一次；这里判错了，用户得自己人工收拾。

补这套评测时当场抓到一个真 bug：`classify` 把 Springer 的
`..._MOESM1_ESM.pdf` 判成了正文 —— 因为改名线自己抄了一份 SI 判据，
而那份没有踩坑 #15 的补丁。两份并成一份之后才对。
**这就是评测的价值：不写它，这个 bug 会一直在那儿，直到某天用户发现附件名乱了。**

加金标 = 往 `decisions.json` 里加一项，不用改任何 .py。每条都要写 `why`。
"""
import json
import os
import tomllib

_HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_HERE, 'thresholds.toml'), 'rb') as _f:
    THRESHOLDS = tomllib.load(_f)

MIN_PASS_RATE = THRESHOLDS['thresholds']['min_pass_rate']


def golden():
    """读金标（dict：classify / split_junk / nested_of / to_tags 四组）。"""
    with open(os.path.join(_HERE, 'golden', 'decisions.json'), encoding='utf-8') as f:
        return json.load(f)
