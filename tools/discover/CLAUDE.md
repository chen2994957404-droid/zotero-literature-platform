# tools/discover · 找新文献 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。

## 这块是什么

**搜全球 → 对照我的库 → 按「跟我多相关」排序 → 按编号收进 Zotero。**

外部检索谁都能调。本工具不可替代的地方是：**只有它知道用户已经有什么、
读过什么、在做什么方向**，所以它回答的不是「有哪些文献」，而是
**「哪几篇值得我现在就读」**。

用户是材料方向研究者（聚硼硅氧烷/动态键弹性体），**不懂编程**。

## 什么时候别用它

- 问「某个问题的答案是什么」→ `tools/ask`（我的库）或 `tools/askworld`（全世界）
- 只想看某个词全球什么情况、不打算收 → `tools/askworld.search`（纯检索，不花 LLM 额度）
- 想看整个方向的地形（谁做了什么、有哪些簇）→ `tools/direction`

## 文件

| 文件 | 干什么 |
|---|---|
| `__init__.py` | 混合检索编排：拆检索式 → 多式检索合并 → 雪球 → 与库对照 → 排序 |
| `find.py` | 命令行找文献（`python -m tools.discover "词"`），结果存下供按编号收 |
| `collect.py` | 按编号收进 Zotero（**收 ≠ 精读**，两个决定分开）|
| `importer.py` | 按 DOI 收进 Zotero（写操作，带机器角色守卫）|
| `match.py` | 与我的库对照：已有/新、相关度、雪球种子、排序 |
| `thesis.py` | 一次性：给毕业论文孤儿附件建 thesis 条目 |
| `selftest.py` | 自测（纯逻辑离线；要 Zotero 的那两条环境不具备时 SKIP）|

## 三条实测结论（改的时候别顺手删掉）

1. **混合检索缺一不可**：单库检索召回 13~35%；加查询扩展 50~95%；
   **再加一轮前后向雪球才 90~100%**。所以默认两条腿都走。
2. **贴题度要用「全部扩展式拼起来」当参照**，不是用户原话（踩坑 #39）。
   用户可能只输入「PBS」这种缩写 —— 它的向量没有语义，拿它当基准
   会把所有候选都判成不贴题，最后一篇不剩。
3. **高被引救不了一篇跑题的文献**（踩坑 #38）。不设贴题门槛时，
   被引 1117 的水凝胶综述、被引 483 的高熵合金会因为「跟库里某篇沾边 + 被引高」
   排到最前面。门槛 0.45，且**杀光时自动放宽** ——
   内部阈值永远不该让用户看到「0 篇」，那看起来像「这个方向没文献」。

## 对外接口

```python
from tools import discover

discover.run_discovery('polyborosiloxane 剪切增稠', limit=25, log=print)
#   → {'queries','contrib','seeds','snow_added','filtered','total_pool','source','rows'}
#     rows = [(paper, match, score)] 已按「跟我多相关」排好序
discover.search('shear stiffening gel', limit=10)   # 只搜一次 OpenAlex，便宜

from tools.discover.match import match_many, pick_seeds, rank, build_index
from tools.discover.importer import import_dois     # 写 Zotero，有角色守卫
```

`run_discovery` 是**面板与命令行共用**的那一份 —— 逻辑只有一份，别再抄第二份。

## 为什么 `match.py` 在这里而不在 `shared/`

下沉规则：**≥2 个工具用到才允许下沉**。它只有本工具一个使用者
（面板调的也是本工具这条线）。REBUILD.md 第四节曾把它划给 `tools/ask`，
但那会逼出 `tools/discover` → `tools/ask` 的跨工具 import，
违反同一份文件第三节的硬规则 2 —— **规则优先于映射表**。

## 怎么验证

```
python tools/discover/selftest.py             # 6 条纯逻辑 + 2 条要 Zotero
python -m tools.discover "polyborosiloxane" --单查询 --不雪球   # 最省的一次真检索
python -m tools.discover.collect --看          # 看上次结果，不写任何东西
```

⚠ `collect` / `importer` / `thesis` 会**写用户的 Zotero 库**，
A 机默认禁止（`ROLE=dev`）。要在编程端试，用测试账号那一档（`ROLE=test`）。
