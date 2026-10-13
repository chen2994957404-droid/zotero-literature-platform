# tools/deepread · 精读一篇文献 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。
> 用户是材料方向研究者（聚硼硅氧烷/动态键弹性体），**不懂编程**。
> 跟他讲话不要提技术细节，用通俗表述说结果。技术决策你自己拿主意。

## 这个工具是什么

**一篇文献（PDF）→ 一份中文图文精读报告**，产物落在证据库那篇的目录里（`curated/<id>/summary*.html`）。

用户怎么用它：在**文献库应用**里打开这篇、点「精读这篇」（`plan()` 先说明要做什么，确认后排队，
`host/app/runner.py` 一篇一篇跑）。2026-10-13 起 Zotero 移出平台：不再打标签触发、不再回写 Zotero。

```
应用里点 → 找本地正本 → MineRU解析 → 精读正文 → (有SI就精读SI) → 合并
                       pdf_parse     main_text   si              merge
                      └──────────────────── run(key) ────────────────┘
```

## 文件

| 文件 | 干什么 |
|---|---|
| `__init__.py` | `run()` 状态机：谁在什么条件下被调、失败了怎么办 |
| `main_text.py` | 正文精读：元数据 → 裁图 → LLM → 确定性插图 → HTML |
| `si.py` | SI（补充材料）精读，支持 PDF 与 .docx |
| `merge.py` | 正文 + SI 合并成一份 |
| `batch.py` | 批量精读 / 批量补 SI / 用 pro 重跑 |
| `cli.py` | 命令行入口（`python -m tools.deepread <KEY>`），只解析参数 |
| `tool.toml` | 工具清单（expose / 花不花钱 / 有什么副作用）—— MCP 服务照它挂 |
| `mcp.py` | 给 agent 的 MCP 面（只做参数转换，不许有逻辑）|
| `README.md` · `SKILL.md` | 给人的说明 · 给 agent 的手册（含**什么时候别用我**）|
| `prompts/main_v2.txt` | **精读的系统提示词，改精读风格/结构就改这里**。改 = 新建 `main_v3.txt` 并把 `main_text.PROMPT_VER` 改成 3，**不许就地改** |
| `prompts/si_v1.txt` | SI（补充材料）精读的系统提示词，规矩同上（`si.PROMPT_VER`）|
| `evals/` | 精读质量评测集：客观快照 + 用户的好/差评价（R5 窗从 `adapters/evalset` 搬来）|
| `selftest.py` | 离线自测（不花钱、不联网） |
| `tests/` | 编排状态机 / 评测器 的离线测试 |

## 状态（`Result.state` / `plan()`）

- 只有正文 → 正文精读；正文 + SI → 全文精读；只有 SI → SI 精读（罕见）；都没有 → 没法精读
**已精读的部分不会重跑**（省钱）。已有正文精读、后来补了 SI，只补 SI 那部分。

## 三条铁的约定（改之前先看懂为什么）

1. **`run()` 只产出文件**；`r.state` 是「实际做成了什么」这个**事实**，
   排队、展示由文献库应用（`host/app`）负责。
2. **`run()` 不抛异常。**单步失败记在 `Result.steps` 里，别的步骤照做 ——
   SI 挂了不该让已经花了钱的正文精读白做。
3. **幂等。**每一步先问 `shared.kernel.jobs`「做过没有、产物还在不在、版本够不够新」，
   做过就跳过。这是省 MineRU + DeepSeek 的钱的地方，别顺手改掉。

## 版本号：改了提示词一定要 +1

`main_text.PROMPT_VER` / `si.PROMPT_VER` 会随每份产物记进状态库。改了提示词范式
却不改版本号，等于告诉系统「旧产物还是新的」，`jobs.stale()` 就查不出待重跑清单。

```python
jobs.stale('main_summary', prompt_ver=3)   # 提示词升到 v3 后，谁该重跑
```

## 实测教训教训（一条都别忘）

1. **max_tokens 必须给足**（32000 起）。DeepSeek V4 的推理链计入 max_tokens，
   给 8000 会产出「只有图没有文字」的废品。`MIN_OK=3000` 是底线：
   不达标就抛 `DeepreadFailed`、**不写盘** —— 废品一旦落盘会被标成已精读，从此不再重跑。
   （SI 线同理，`_BUDGETS = (16000, 32000)`，2026-08-27 才补上。）
3. **输入不要粗暴截断**。V4 有 1M 上下文；早期截到 40000 字符正好切掉结论与机理讨论。
4. **裁图不要自己重写**。用 `shared.domain.figure_crop` —— 踩坑 #7 的全部智慧固化在那儿。
5. **插图是脚本干的，不是模型干的**。模型只输出【图N】标记，图由 `insert_figures` 插。
7. 长任务会超过 MCP 的 60 秒调用上限 —— 用「后台发起 + 轮询文件结果」，别干等。

## 改完怎么验证

```
python tools/deepread/selftest.py             # 本工具自测，不花钱
python -m pytest tools/deepread -q            # 编排/判据/接线三组离线测试
python host/doctor/health_check.py --offline  # 离线体检，必须全绿
python -m tools.deepread <KEY> --force        # 拿真实文献实测（旧版自动备份 .bak）
```
判废标准：精读正文 < 3000 字基本是失败品，正常在 8000~13000 字。
