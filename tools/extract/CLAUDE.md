# tools/extract · 结构化抽取编排 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。

## 这块是什么

**一篇文献的正文 `parsed/full.md` **加上** SI `si_parsed/full.md`
→ 对齐的机器可读字段 → 并入横向对比表。**

**SI 必须读**（2026-08-28，踩坑 #68）：投料量、配比、温度时间几乎只写在补充材料里，
论文正文不写。不读它 `synthesis_conditions` 就只能是 N/A。
SI 的 `full.md` 是精读那一步早就解析好的，读它不花任何钱。

它组合了四样东西，自己不解决任何原子问题：

```
shared.kernel.paths（去哪读、往哪写） + shared.domain.schema（抽什么、怎么问、怎么摆）
+ shared.adapters.llm_client（谁来抽） + shared.kernel.jobs（谁抽的、哪版字段、失败在哪）
```

## 文件

| 文件 | 干什么 |
|---|---|
| `__init__.py` | 抽一篇的编排：读料 → 调模型 → 自检重抽 → 落盘 → 出表 |
| `batch.py` | 三条批量线：精层批量 / 缺 full.md 先解析 / 粗层全库（本地模型） |
| `cli.py` | 命令行入口（`python -m tools.extract`），只解析参数 |
| `tool.toml` | 工具清单（expose / 花不花钱 / 有什么副作用）—— MCP 服务照它挂 |
| `mcp.py` | 给 agent 的 MCP 面（只做参数转换，不许有逻辑）|
| `README.md` · `SKILL.md` | 给人的说明 · 给 agent 的手册（含**什么时候别用我**）|
| `prompts/` | 系统提示词（`<名>_v<N>.txt`）。**只增不改**：改措辞就新建下一版，旧版留着 |
| `evals/` | 评测：23 条金标，验「抽完之后的理解」（综述/档次/有值/性能拆解）。**「模型抽得准不准」那一半还缺**，要人工核对过的真实记录 |
| `domain_filter.py` | 从全库筛出「本方向」的干净子表（剔除跑题与 N/A） |
| `compare_models.py` | 本地 vs 云端 A/B 三指标对比，**只打印不写盘**（踩坑 #16） |
| `wizard.py` | 给人双击的重抽向导（列清单 → 问模型 → 跑 → 报花了多少钱） |
| `selftest.py` | 离线自测（不调 LLM、不碰真实数据） |

**两个档次，同一套字段**（对称于向量化的粗细两层）：

| 档 | 料 | 模型 | 入口 |
|---|---|---|---|
| 精层 | MineRU 全文 `full.md` + SI | 云端 DeepSeek | `batch.extract_many` |
| 粗层 | Zotero 自带全文索引 | 本地 Ollama | `batch.coarse_all` |

**精层结果绝不被粗层覆盖**，即使 `--rebuild`（踩坑 #16 的代价买来的）。

## 对外接口

```python
from tools import extract

extract.run(key)              # 抽一篇 + 并入对比表；抽过且字段没升版就跳过
extract.extract_one(key)      # 只抽，不出表（批量时用，最后统一出一次表）
extract.write_compare_table() # 读全部 structured/*.json 重出两张表
extract.stale_keys()          # 字段升版后，谁该重抽
extract.si_pending_keys()     # 有 SI 却是「没读 SI 时」抽的，谁该重抽（花钱前先看这个）
extract.si_text(key)          # 这篇的 SI 全文（取过合成相关章节）；没有就空串
```

`run()` **不抛异常**：失败返回 None 并记进状态库。
理由与精读线一致 —— 抽取失败不该让已经花了钱的精读和回写白做。

## 质量怎么保：抽一遍 + 全库免费抽检（2026-09-07 改）

原先每篇都跑「自我评估重抽循环」：抽完让模型对照原文自查漏抽与幻觉，
有问题带着反馈重抽（借鉴 KnowMat 的骨架，用自己的公理件实现）。
它有用，但**代价是把整篇原文再发一遍**，一篇的花销直接乘三 ——
实测 29 篇就把百炼某个模型的 100 万免费额度吃光了。

用户拍板改成：**抽一遍，事后抽检**（原话：「要循环这么多遍吗，
如果质量稳定没问题的话抽检一下就行吧」）。

```
python -m tools.extract.audit              # 全库抽检，按可疑程度排序（免费、秒级）
python -m tools.extract.audit --key ABCD1234   # 看某一篇具体哪些数字对不上
```

`audit` 把抽出来的每个数字回原文逐字找（`schema.number_grounding`，纯字符串比对）：
找不到的要么是单位换算，要么是编的 —— 排序 + 人看最差的几篇，一眼分得出。
顺带查「数值挂在不存在的样品上」这种结构性错。

**自检循环仍在**（`EXTRACT_NO_EVAL=1` 关掉；本地 ollama 自动跳过，
小模型的自检结论不可信）。区别只是：**它不再是默认要跑满全库的那一步。**

## 想改什么，去哪改

| 你想改 | 改哪 |
|---|---|
| 抽哪些字段、字段怎么描述 | `domain/schema`（**并把 `SCHEMA_VER` +1**）|
| 对比表长什么样 | `domain/schema.compare_table` |
| 用哪个模型抽 | 控制面板的「结构化抽取 用的模型」（`EXTRACT_MODEL`）|
| 走云端还是本地 | 环境变量 `EXTRACT_PROVIDER=ollama` |
| 读写路径 | `shared/kernel/paths`（**不要在这里手拼 `data/` 的路径**，守卫会拦）|

## 怎么验证

```
python tools/extract/selftest.py                  # 8 条，不调 LLM、不碰真实数据
python host/doctor/health_check.py --offline      # 离线体检，必须全绿
python -m tools.extract <KEY>                     # 真抽一篇（花钱）
python -m tools.extract --si-pending --list       # 只列清单，不花钱
```

## 抽完不用再管查询库了（R7 窗改的）

这里曾经抽完顺手 `paperdb.rebuild()` —— 那是 `tools` 调 `tools`，违反硬规则 2。
R7 窗把责任挪对了地方：**索引的新鲜度是索引自己的事**，
`paperdb.query()` 每次比一眼时间戳，比源 JSON 旧就自己重建（秒级、不花钱）。

真正的毛病不在那行 import，而在责任放错了地方：让写入方负责，
就得每个写 JSON 的人都记得刷一次，漏一个用户就查到旧数据，**而且不报错**。

## MCP 上的两面（2026-09-01 起）

`extract_one`（抽**一篇**）是 **tool**，每次调用都弹窗确认；
全库增量抽取仍是 **prompt**，只能人点。

⚠ 抽一篇**可能超过 MCP 约 60 秒的调用上限**（长文过一次大模型）。
超时也不要紧：产物照样落盘，而且这一步幂等（抽过就跳过），
再调一次几乎不花钱 —— 这句话也写进了工具的返回文本里。

判据与两道闸的守卫见 `host/mcp/CLAUDE.md`。
