# pipelines/extract · 结构化抽取编排 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。

## 这块是什么

**一篇文献的正文 `parsed/full.md` **加上** SI `si_parsed/full.md`
→ 对齐的机器可读字段 → 并入横向对比表。**

**SI 必须读**（2026-08-28，踩坑 #68）：投料量、配比、温度时间几乎只写在补充材料里，
论文正文不写。不读它 `synthesis_conditions` 就只能是 N/A。
SI 的 `full.md` 是精读那一步早就解析好的，读它不花任何钱。

它组合了四样东西，自己不解决任何原子问题：

```
core.paths（去哪读、往哪写） + domain.schema（抽什么、怎么问、怎么摆）
+ adapters.llm_client（谁来抽） + core.jobs（谁抽的、哪版字段、失败在哪）
```

这是 watcher 里**最后一个 subprocess** 的去处（阶段 3 下半，2026-08-27）。
搬进来之后，精读流水线从头到尾不再拉任何子进程。

## 对外接口

```python
from pipelines import extract

extract.run(key)              # 抽一篇 + 并入对比表；抽过且字段没升版就跳过
extract.extract_one(key)      # 只抽，不出表（批量时用，最后统一出一次表）
extract.write_compare_table() # 读全部 structured/*.json 重出两张表
extract.stale_keys()          # 字段升版后，谁该重抽
extract.si_pending_keys()     # 有 SI 却是「没读 SI 时」抽的，谁该重抽（花钱前先看这个）
extract.si_text(key)          # 这篇的 SI 全文（取过合成相关章节）；没有就空串
```

`run()` **不抛异常**：失败返回 None 并记进状态库。
理由与精读线一致 —— 抽取失败不该让已经花了钱的精读和回写白做。

## 自我评估重抽循环

抽完对照原文自检（漏抽 / 幻觉），有问题就带着反馈重抽，最多两轮。
借鉴 KnowMat 的骨架，但用自己的公理件实现，**没有引入任何框架依赖**。

- `EXTRACT_NO_EVAL=1` 关掉（省钱）
- provider 是本地 ollama 时自动跳过 —— 小模型的自检结论不可信，
  跟着它改反而更差

## 想改什么，去哪改

| 你想改 | 改哪 |
|---|---|
| 抽哪些字段、字段怎么描述 | `domain/schema`（**并把 `SCHEMA_VER` +1**）|
| 对比表长什么样 | `domain/schema.compare_table` |
| 用哪个模型抽 | 控制面板的「结构化抽取 用的模型」（`EXTRACT_MODEL`）|
| 走云端还是本地 | 环境变量 `EXTRACT_PROVIDER=ollama` |
| 读写路径 | `core/paths`（**不要在这里手拼 workflow_data**，守卫会拦）|

## 怎么验证

```
python pipelines/extract/selftest.py    # 5 条，不调 LLM、不碰真实数据
python 数据抽取/extract_structured.py <KEY>   # 真抽一篇（花钱）
```
