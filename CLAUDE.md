# 文献自动化科研平台 · 给 Claude 的说明

围绕 Zotero 的文献科研平台。用户是材料方向研究者（聚硼硅氧烷/动态键弹性体），**不懂编程**。
本文件是**唯一入口**：想帮用户干活看【第一部分】，想改代码看【第二部分】。

<!-- AUTO:结构 开始 · 由 host/codegen/handover.py 生成，勿手改 -->

## 项目结构（自动同步，**不要 glob 根目录**）

> `workflow_data/` 有 3000+ 个数据文件，glob 根目录会直接淹掉你的上下文。
> 下面这棵树就是全部结构，不必再去扫。

```
docs/                    ← 文档（16 份）
host/  ← 平台自身：让平台活着的东西（没人 import 它）（5 块）
    codegen、deploy、doctor、mcp、panel
launch/ （0 个脚本）
shared/  ← 共用件：被 ≥2 个工具用到才允许住这里
    kernel/  ← 基础设施：谁都依赖它，它不依赖任何人（12 块）
        cli、config、proc_lock、prompts、subproc、errors.py、heartbeat.py、jobs.py、log.py、mcp_prompt.py、paths.py、role.py
    domain/  ← 纯逻辑：不联网、不知道文件放在哪（4 块）
        bibliometrics、figure_crop、schema、si_filter
    adapters/  ← 外接口：唯一允许联网/用第三方库的一环（11 块）
        crossref、embed、llm_client、openalex、pdf_parse、query_expand、sciverse、snowball、vectordb、wechat_seed、zotero_client
specs/ （0 个脚本）
tests/ （10 个脚本）
    test_adapters_vectordb.py、test_architecture.py、test_artifact_gaps.py、test_core_heartbeat.py、test_core_jobs.py、test_core_log_errors.py、test_core_paths.py、test_core_role.py…
tools/  ← 工具切片：一个工具 = 一个自包含的包（10 块）
    ask、askworld、curate、deepread、digitize、direction、discover、extract、library、paperdb

根目录文件：CLAUDE.md、LICENSE、README.md、REBUILD.md、pyproject.toml、requirements.txt、控制面板.bat、更新平台.bat、比一比两个模型.bat、精读监听.bat、诊断报告.bat、重抽缺SI的文献.bat、重跑精读PRO.bat

（workflow_data/ 是数据目录，3000+ 文件，**不要去 glob 它**）
```

**可枚举的块 30 个**（`tools/` 工具切片 + `shared/` 共用件，每个都有 `__init__.py` 与 `selftest.py`）

进度、健康状况、下一步做什么 → 见 `HANDOVER.md`

<!-- AUTO:结构 结束 -->

## 🚧 正在进行框架重构 —— 新窗口先读 `REBUILD.md`

用户正在按窗口分工做一次框架重构。**如果他说「做下一窗」,读 `REBUILD.md`,
找到台账里第一个没打勾的窗,只做那一窗。** 那份文件是自给自足的,不必读本文件之外的东西。

## ⚠ 两台机器 —— 你在 A 机（编程端）

本项目跑在两台机器上。**A 机 = 改代码的唯一入口；B 机 = 主力机，数据与服务的权威副本，
没有 Claude Code。** A 机默认不写 Zotero、不跑 watcher、不跑花钱的批量作业。

⚠ **2026-08-27 起 A 机多了独立的测试 Zotero 账号（`ROLE=test`），
这一档允许写、允许跑 watcher —— 别再照旧文档说「A 机一律不许写」。**

涉及写 Zotero / 部署到 B / 连 B 排查 / 起常驻服务 → **读 `two-machines` skill**。

## 📌 新对话第一件事：读 `HANDOVER.md`（**别先 glob 根目录**）

上面的目录树就是全部结构，不必再扫 —— `workflow_data/` 有 3000+ 个数据文件，
glob 根目录会直接淹掉上下文（实测：前 100 个结果全是精读图片）。

`HANDOVER.md` 由 `python host/codegen/handover.py` 自动生成，全部抓自系统真实状态：
当前健康状况、最近十次改动、评测集进展、待办、最近踩的坑。
**本文件说「这个项目是什么」，交接文件说「我们做到哪了」，两者缺一不可。**

## 目录结构（2026-08-30 重构，R1 窗）

```
tools/    工具切片：一个工具 = 一个自包含的包
          deepread 精读 · extract 抽取 · paperdb 查询库 · digitize 图表（R2 窗切好）
          ask 库内问答 · askworld 问全世界 · discover 找新文献 ·
          direction 方向地图 · curate 库房维护（R3 窗切好）
          library 查 Zotero 库（R4 窗从 MCP 的 zotero_server 切出来，共 10 个）
          每个工具都有五件套：tool.toml / cli.py / mcp.py / README.md / SKILL.md
shared/   共用件：kernel（基础设施）/ domain（纯逻辑）/ adapters（唯一能联网的一层）
host/     平台自身：panel 面板 · doctor 体检 · deploy 部署 · codegen 生成器 · mcp 协议层
```

雪球（snowball）**不单独成工具**：读过代码后判定它是纯 API 包装，
留在 `shared/adapters/snowball/`，编排那一句在 `tools/discover` 里（R3 窗判定，理由见 REBUILD 台账）。

**每个文件夹里都有自己的 `CLAUDE.md`。** 用户只选中某个文件夹时，那份就是完整上下文；
在根目录（现在这里）你能看到全部，负责跨文件夹的改动与全局判断。

用户的操作入口是根目录的 **控制面板.bat**（本地网页）。人看的地图在 `README.md`。

## 🧰 按需加载的 skill（`.claude/skills/`）—— 别把它们的内容抄回本文件

本文件只留「每次会话都要知道」的东西。下面四份是**按需**加载的，
遇到对应场景**主动去读**，不要凭记忆作答：

| skill | 什么时候读 |
|---|---|
| `troubleshoot` | 报错 / 卡住 / 没反应 / 数字不对 / 明明改了却没变 |
| `code-redlines` | **要动任何 .py 之前**（七条红线 + 四环依赖 + 验证顺序） |
| `research-first` | 要做新东西、选技术路线、或要断言外部世界现状 |
| `two-machines` | 写 Zotero / 部署 / 连 B / 起常驻服务 |

---

# 第一部分 · 能力速查（用户提科研需求时看这里）

**用户不懂代码，别跟他讲技术细节。他说需求，你选工具执行，用大白话汇报结果。**

## 用户可能提的需求 → 你该用什么

| 用户说 | 你怎么做 |
|--------|---------|
| "库里有没有XX这篇" "最近加了什么" "有哪些标签" | `python -m tools.library search XX`（只读、免费、秒回；还有 item / pdf / fulltext / collections / tags / recent）|
| "我库里关于XX有什么？" "帮我查查XX" | `python -m tools.ask "问题"`（RAG 问答，中文答+附来源；**只是找某篇在不在库里，用上面那条更便宜**）|
| "帮我找XX方向的文献" "补充点XX的文献" | `python -m tools.discover "关键词"`（拆检索式+雪球+按「跟他多相关」排序）；只要一份简单列表用 `tools.discover.search(query)` |
| "帮我横向比较XX" "这方向有什么规律/空白" | 读 `workflow_data/structured/compare.md`（研究论文横向对比表）；PBS 方向另有 `compare_PBS.md` |
| "精读某篇文献" | 让他在 Zotero 打「待处理」标签即可。**状态机自动判断**：只有正文→精读正文→标「正文精读」；有SI→连SI一起精读并合并→标「全文精读」；已精读过的只补缺的部分不重跑。服务已开机自启。 |
| "把某批文献的数据抽出来" | `python -m tools.extract KEY1 KEY2 --parse`（自动 MineRU 解析+DeepSeek 精抽）|
| "全世界有没有人做过XX" "查查外面的文献" | `python -m tools.askworld "问题"`（Sciverse 取原文片段作答，**带出处**；要 SCIVERSE_KEY）|
| "把论文图里的曲线变成数据" | `tools/digitize` 的 `digitize()`，**必须用云端大模型**（本地7B会编假数据）|
| "帮我想想研究方向/idea" | 读 compare 表做横向关联分析（找机理×性能的空白格），或 `python -m tools.direction.brainstorm` |

## 现成数据资产（在哪找什么）

- `workflow_data/structured/compare.md` — 研究论文横向对比表（2026-08-28 实测 175 条：39 精层 + 136 粗层）
- `workflow_data/structured/compare_reviews.md` — 5 篇综述单列
- `workflow_data/structured/compare_PBS.md` — 聚硼硅氧烷方向精层子表（10 篇，含真实数值）
- `workflow_data/structured/<KEY>.json` — 每篇的结构化字段
- `workflow_data/library/<KEY>/` — 精读过的文献（parsed/full.md 全文 + summary.html 中文精读）
- `workflow_data/vector_db/` — 向量库（9105 块，供 `tools/ask` 检索）

## 代码四环（可直接 import 复用）

完整清单见上方「项目结构」自动区块。判据：**什么会让它需要改**。

| 环 | 什么会让它改 | 能联网 |
|---|---|---|
| `shared/kernel/` | 几乎不会（路径/配置/日志/异常/参数/锁） | 否 |
| `shared/domain/` | 只有我们自己想法变了（算法、格式、schema） | 否，且不许知道文件放在哪 |
| `shared/adapters/` | 外部世界变了（API 换版本、模型换代、换向量库） | **只有这一环** |
| `tools/` | 需求一变就变（把上面三者按顺序组合成一个工具） | 否 |

「只有 adapters 可以联网」就是**「换掉 MineRU 只改一个文件」的全部保证**，
架构守卫会强制它。→ 细则见 `code-redlines` skill。

## ⚠ 最高优先级：先看真实世界，别用记忆代替调研

宪法【零号判据】（2026-08-09 立）。用户原话：
> **你下意识回答我的往往还是预训练的结果，我们还是要主动去看真实实时的世界是怎么样。**

- 涉及**外部世界现状**（有无某功能、定价、限额、行业惯例）→ **必须查**
- 涉及**具体数字** → 查到出处才说，查不到就说查不到
- 涉及**外部 API 行为** → 真实调用实测

> **听起来很具体的数字最像事实，也最可能是编的。**
> 自查：说完一句判断，问自己 —— 这是**刚查到的**，还是我**本来就"知道"的**？后者打问号。

**停止判据**：这次调研能不能改变我接下来的做法？能就查，不能就别查。
→ 四步调研法与完整论证见 `research-first` skill。

## 语言约定（重要）

- **给用户看的用中文**：精读 HTML、问答答案。
- **机器数据用原生英文**：结构化抽取、图表数据（用户读英文文献，中间数据给 LLM 用，不翻译）。

## 模型分工（别搞混）

- 向量化：`bge-m3`（本地免费，只做文本→向量）
- 结构化抽取：`deepseek-v4-pro`（输出少用 pro 更准，几乎不增成本）
- 精读：`deepseek-v4-flash`（输出 9000 字长文，用 flash 省钱）
- 图表数字化：**云端大模型必须**（硅基流动 Qwen3.5-397B/3.6-27B）；本地 7B 会编假数据
- 原则：**输出少的活上 pro，输出多的上 flash**

## 运维现状（不用管，已自动化）

两个自启任务（登录 + 每小时保活）：`ZoteroLiteratureWatcher`（看门狗→watcher，
用户打「待处理」标签即自动精读）、`OllamaService`（本地 Ollama，带正确 `OLLAMA_MODELS`）。

**密钥存在系统凭据库**（Windows 凭据管理器），硬盘上没有明文。
统一走 `shared/kernel/config` 的 `get_key()`，加载顺序：环境变量 → 系统凭据库 → `.env`。
用户在**控制面板**里填写与切换。

服务报错、Ollama 失明、面板改了不生效 → **读 `troubleshoot` skill**。

---

# 第二部分 · 开发约定（要改代码时看这里）

## 最高纲领

**先读 `docs/架构宪法_第一性原理.md`** —— 它定义整个系统怎么构筑：公理→定理→组合，
三条铁律，以及「按稳定性决定自己做还是用现成」的首要判据。任何改动服从它。

## 接手先读（别边探边拼）

`docs/变更记录.md`（最新状态）→ `docs/踩坑记录.md`（已知坑）→
`docs/架构宪法_第一性原理.md` → `docs/数据契约.md`。别走到哪读到哪、靠猜（教训见踩坑 #14）。

## ⚠ 正在进行架构重构 v2（2026-08-26 起）

v2（四环）已被本次「按工具切片」的重构取代 —— **现在的唯一施工文件是 `REBUILD.md`**，
台账在它第五节。`docs/架构重构_v2总体设计.md` 只作历史参考，别照它施工。
**做到哪一窗 → `REBUILD.md` 的台账**（别在这里维护第二份）。

**装一次才能跑**（换电脑/重装后必做）：`pip install -e . --no-deps`

## 代码规范（红线）

**改任何 .py 之前先读 `code-redlines` skill**（七条红线 + 四环依赖 + 三件套准入 + 验证顺序），
原文在 `docs/代码规范_标准脚本模板.md`。

## 验证自主性

有 Windows MCP，可直接在用户机器跑验证，**无需每次停下来问**：
- 自主做：只读/验证类命令、A/B 对比、单篇验证、读脚本读数据 → 跑完直接报结果。
- 先问用户：全库重抽（花钱）、覆盖/删除数据、影响真实 Zotero 库的写操作、
  方向性抉择（改 schema、换技术路线 —— 这是用户的领域判断）。
- 原则：可还原零成本的自己跑；有副作用/花钱/不可逆的先说清代价再问。

## 日志纪律（每次改动都要）

- 技术发现/踩坑 → 当场追加 `docs/踩坑记录.md`（编号 + 现象/根因/解法）
- 改代码/删数据/运维 → 当场记 `docs/变更记录.md`
- 需要改架构但还没做 → 记 `docs/待办与需求.md`
- 写中文用 Python `io.open(...encoding='utf-8')` 追加，避开 PowerShell 的 GBK 乱码
- **每个改动 Git commit**

## 已知环境坑（速记，细节见 `troubleshoot` skill）

- PowerShell 控制台中文乱码：**先用 Read 工具确认真实内容**，再判断是显示还是数据。
- **MCP 调用约 60 秒超时**：精读、全库抽取、大模型读图会超时但后台继续 —— 发起后轮询文件。
- 一切外部 API 先用真实数据实测（最重要的一条）。

## 其他文档

`docs/架构总览.md`（数据流）· `docs/演进规划与模块地图.md` ·
`docs/对标报告_我们的思路 vs 前沿.md` · `docs/积木采购清单_可借鉴的开源积木.md` ·
`docs/正文数据关联_方向说明.md` · `docs/视觉模型选择_参考.md` · `docs/待办与需求.md`
