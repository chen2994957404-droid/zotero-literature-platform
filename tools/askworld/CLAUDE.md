# tools/askworld · 问全世界 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。

## 这块是什么

**向全球文献提一个科学问题 → Sciverse 取回可引用的原文片段 →
大模型结合片段用中文作答 → 附出处（第几页都有）。**

**答案只允许基于取回的片段**。系统提示词里写死了「不要用你自己的知识补充」——
本工具的全部价值在于**可追溯**，一旦允许自由发挥就退化成一个普通聊天框。

用户是材料方向研究者（聚硼硅氧烷/动态键弹性体），**不懂编程**。

## 什么时候别用它

- 问「我读过的文献里怎么说」→ 用 `tools/ask`（本地向量库，答得深且免费）
- 想补库、决定读哪几篇 → 用 `tools/discover`（会按「跟你多相关」排序）
- 没配 `SCIVERSE_KEY` → 本工具直接不可用，别让用户白等（`available()` 先问一句）

## 文件

| 文件 | 干什么 |
|---|---|
| `__init__.py` | 问答编排（`ask_world`）+ 纯检索（`search_world`）|
| `cli.py` | 问答命令行（`python -m tools.askworld "问题"`）|
| `__main__.py` | 一行壳，转给 `cli.main()` |
| `tool.toml` | 工具清单（expose / 花不花钱 / 有什么副作用）—— MCP 服务照它挂 |
| `mcp.py` | 给 agent 的 MCP 面（只做参数转换，不许有逻辑）|
| `README.md` · `SKILL.md` | 给人的说明 · 给 agent 的手册（含**什么时候别用我**）|
| `prompts/` | 系统提示词（`<名>_v<N>.txt`）。**只增不改**：改措辞就新建下一版，旧版留着 |
| `evals/` | 评测：可追溯性（出处到页码、跑题证据筛掉、没证据不硬答、检索式转英文）。**答案质量那一半还缺** |
| `search.py` | 检索命令行（`python -m tools.askworld.search "词" 20 --impact`）|
| `selftest.py` | 离线自测（不联网、不调 LLM）|

## 两条硬约束（改的时候别顺手删掉）

1. **中文问题必须先转英文**（踩坑 #35 实测）：Sciverse 按提问语言加权。
   中文问「聚硼硅氧烷的剪切硬化机理」召回的是硼硅玻璃辐照、炉渣、LTCC 陶瓷；
   同一问题英文问，相关度 0.97 且全部对口。转换逻辑在
   `shared/adapters/query_expand.to_english`，**不要在这里重写一份**。
2. **相关度低于 0.60 的片段一律丢掉**。实测 0.35~0.5 的全是跑题的，
   混进上下文会让答案跟着跑偏。宁可少给几条。

## 对外接口

```python
from tools import askworld

askworld.ask_world('剪切硬化机理是什么', top_k=8, year_from='2020')
#   → {'answer': 带[1][2]标注的中文, 'evidence': [...], 'query_used': 英文式}
askworld.search_world('polyborosiloxane', limit=20, prefer='impact')
#   → {'items': [... 每条带 in_library], 'total': 全球命中数}
askworld.available()      # 有没有配 Sciverse 密钥
```

## 想改什么，去哪改

| 你想改 | 改哪 |
|---|---|
| 相关度门槛 | `MIN_SCORE`（本文件夹 `__init__.py`）|
| 用哪个模型作答 | 控制面板的 `ASK_MODEL` |
| 中文转英文的策略 | `shared/adapters/query_expand` |
| 换检索源（Sciverse → 别家）| `shared/adapters/sciverse`（这里一行不用动）|

## 怎么验证

```
python tools/askworld/selftest.py             # 6 条，全离线
python -m tools.askworld "剪切硬化机理"        # 真问一次（要 SCIVERSE_KEY + DEEPSEEK_KEY）
python -m tools.askworld.search "polyborosiloxane" 10
```
