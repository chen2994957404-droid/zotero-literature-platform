# literature-platform · 给所有 agent 的正本

文献自动化科研平台，**核心是证据库**；用户自己用的入口是**文献库应用**（`host/app`，浏览器开 http://127.0.0.1:8780）。
**Zotero 已于 2026-10-13 移出平台**（旧代码在 git 标签 `zotero-before-removal`；用户以后会按新需求单独做 Zotero 功能）。
用户是材料方向研究者（聚硼硅氧烷 / 动态键弹性体），
**不懂编程**。给他看的一律用中文通俗表述，别讲技术细节。

**这份是唯一入口。** 帮他干活看【第一部分】，改代码看【第二部分】。
`CLAUDE.md` 只是指向这里的一行。
**「这件事该动哪个文件夹」单独有一份：根目录的 `各部分的关系.md`。**

<!-- AUTO:结构 开始 · 由 host/codegen/handover.py 生成，勿手改 -->

## 项目结构（自动同步，**不要 glob 根目录**）

> `data/` 有 3000+ 个数据文件，glob 根目录会直接淹掉你的上下文。
> 下面这棵树就是全部结构，不必再去扫。

```
docs/  ← 跨工具的档案（另有 4 份日志直接躺在下面）
    explain/（8）、howto/（3）、reference/（19）、incidents/（2）  ← 为什么 / 怎么做 / 事实 / 坑
host/  ← 平台自身：让平台活着的东西（没人 import 它）（9 块）
    app、codegen、daily、deploy、doctor、ingest、mcp、panel、watcher
launch/  ← 给人双击的入口（常用 4 个；不常用/ 里 6 个备用与开发用）
    取全文用的浏览器.bat、控制面板.bat、设置与密钥.bat、运行与日志.bat
    不常用/：更新平台.bat、比一比两个模型.bat、诊断报告.bat、连上文献平台（Antigravity用）.bat、重抽缺SI的文献.bat、重跑精读PRO.bat
outputs/  ← 外部 agent 的产物 / 草稿，不进版本库
scratch/  ← 外部 agent 的产物 / 草稿，不进版本库
shared/  ← 共用件：被 ≥2 个工具用到才允许住这里
    kernel/  ← 基础设施：谁都依赖它，它不依赖任何人（15 块）
        cli、config、proc_lock、prompts、subproc、budget.py、catalog.py、errors.py、heartbeat.py、jobs.py、log.py、mcp_prompt.py、paths.py、role.py、units_store.py
    domain/  ← 纯逻辑：不联网、不知道文件放在哪（6 块）
        figure_crop、glossary、libmatch、numcheck、schema、stopwords
    adapters/  ← 外接口：唯一允许联网/用第三方库的一环（24 块）
        ccdc、chemdb、cnki、crossref、embed、jcr、llm_client、ner、openalex、pdf_fetch、pdf_parse、polyinfo、pubchem、query_expand、sciverse、scopus、semanticscholar、sentences、snowball、tansoole、typesafe、units、unpaywall、vectordb
tests/ （6 个脚本）
    test_architecture.py、test_budget.py、test_llm_routing.py、test_no_undefined_names.py、test_principles.py、test_types.py
toolbox/ （0 个脚本）
tools/  ← 工具包：一个工具 = 一个自包含的包（12 块）
    ask、askworld、deepread、digitize、direction、discover、extract、getpdf、journalwatch、library、litsearch、paperdb

根目录文件：AGENTS.md、BA_TRIS_DMAEMA_三元共聚20g小试实验指南.md、CLAUDE.md、LICENSE、README.md、REBUILD.md、conftest.py、pyproject.toml、pyrightconfig.json、requirements.txt、各部分的关系.md

（data/ 是数据目录（五层），3000+ 文件，**不要去 glob 它**）
```

**可枚举的模块 47 个**（`tools/` 工具包 + `shared/` 共用件，每个都有 `__init__.py` 与 `selftest.py`） · **还没切进 `tools/` 的老文件夹 1 个**

进度、健康状况、下一步做什么 → 见 `HANDOVER.md`

<!-- AUTO:结构 结束 -->

## 📌 新对话第一件事：读 `HANDOVER.md`（**别先 glob 根目录**）

**出了问题、或要动一块之前**：读 `docs/reference/系统认识_各块机制与弱点.md`（生成物）——
每块靠什么外部东西、踩过哪些坑、最近改过什么，按块聚合。知道它怎么做的，才猜得到它会坏在哪。

上面那棵树就是全部结构，不必再扫 —— `data/` 有 3000+ 个数据文件，
glob 根目录会直接淹掉上下文（实测：前 100 个结果全是精读图片）。

`HANDOVER.md` 由 `python host/codegen/handover.py` 生成，全部抓自系统真实状态：
当前健康状况、最近十次改动、评测集进展、待办、最近踩的坑。
**本文件说「这个项目是什么」，交接文件说「我们做到哪了」，两者缺一不可。**

## ⚠ 两台机器 —— 你在 A 机（编程端）

**A 机 = 改代码的唯一入口；B 机 = 主力机，数据与服务的权威副本，没有 Claude Code。**
A 机默认不跑常驻服务、不跑花钱的批量作业（`ROLE=dev`）；A 机现在是 `ROLE=test`（测试档，放行，产物只在本机）。

涉及部署到 B / 连 B 排查 / 起常驻服务 → **读 `two-machines` skill**。

## 🧰 按需加载的 skill（`.claude/skills/`，全部由生成器产出）

本文件只留「每次会话都要知道」的。下面这些**按需**读，别凭记忆作答：

| skill | 什么时候读 |
|---|---|
| `troubleshoot` | 报错 / 卡住 / 没反应 / 数字不对 / 明明改了却没变 |
| `code-redlines` | **要动任何 .py 之前**（七条强制规范 + 四条硬规则 + 验证顺序）|
| `research-first` | 要做新东西、选技术路线、或要断言外部世界现状 |
| `deep-research` | 用户要**研究透一个方向 / 判断想法有没有人做过 / 出带出处的调研报告**：通用章法（分面 + 同义词族 → 四种经典检索策略 → 滚雪球准则 → 质疑空集 → 饱和判据 → 报告形状），不绑定课题 |
| `two-machines` | 部署 / 连 B / 起常驻服务（连机器的机械细节在**全局**技能 `remote-machine`，源在 `toolbox/remote-machine/`）|
| 十个工具各一份 | 要用某个工具时（含**什么时候别用我**）|

---

# 第一部分 · 能力速查（用户提科研需求时看这里）

| 用户说 | 你怎么做 |
|--------|---------|
| 「库里有没有 XX 这篇」「手上有哪些文献」| `python -m tools.library 库 XX`（**先问证据库**，零网络、秒回；结果标出每篇有正文/SI/已解析/已精读没有）|
| 「按 DOI / 标题词 / 通讯作者 / 团队 / 年份 / 期刊找」| `python -m tools.library 检索 …`（他自己用的是文献库应用里的检索页，同一套）|
| 「某个研究团队有哪些文章」| `python -m tools.library 团队 XX`（名单在 `data/state/teams.json`，人工查证）|
| 「我库里关于 XX 有什么？」| `python -m tools.ask "问题"`（RAG，中文答 + 附来源。**只是找某篇在不在，用上面那条更便宜**）|
| 「帮我找 XX 方向的文献」| `python -m tools.discover "关键词"`（拆检索式 + 雪球 + 按「跟他多相关」排序）|
| 「我在找**新方向**」「别被我现有的库拖累」| `python -m tools.discover "关键词" --新方向`（只按贴题排，不按近库排）；或直接用 `lit_search` 对抗式检索（它本来就不看库）。**别用 `ask`** —— 那是问他自己的库 |
| 「把这个方向研究透」「我想在 A 上引入 B，有人做过吗」| 读 `deep-research` skill 照章法走：`library_retrieve`（库内找原料，零成本）→ `lit_search`（标 可读/库里有）→ `library_outline`/`library_section`（点节、段、表）→ `library_refs`（库内顺引用）→ 报告带出处 |
| 「帮我横向比较 XX」「这方向有什么空白」| 读 `data/serving/structured/compare.md`；PBS 方向另有 `compare_PBS.md` |
| 「精读某篇文献」| 让他在**文献库应用**里打开这篇、点「精读这篇」（会先说明要做什么、要花钱，确认后排队）。**状态机自动判断**：只有正文→正文精读；有 SI→全文精读；已精读的只补缺的 |
| 「把某批文献的数据抽出来」| `python -m tools.extract KEY1 KEY2 --parse` |
| 「拉伸强度超过 10 MPa 的有哪些」| `python -m tools.paperdb --find ...`（能比大小的数值库）|
| 「全世界有没有人做过 XX」| `python -m tools.askworld "问题"`（Sciverse 取原文片段，**带出处**）|
| 「把论文图里的曲线变成数据」| `python -m tools.digitize 图片路径`，**必须用云端大模型**（本地 7B 会编假数据）|
| 「帮我想想研究方向」| 读 compare 表找「机理 × 性能」的空白格，或 `python -m tools.direction` |
| 「期刊分级 / 这本刊可不可信」| `python -m tools.journalwatch.grading --list` |

## 现成数据资产

- `data/serving/structured/compare.md` — 横向对比表（2026-08-28 实测 175 条：39 精层 + 136 粗层）
- `data/serving/structured/compare_reviews.md` · `compare_PBS.md` — 综述单列 · PBS 精层子表（10 篇）
- `data/serving/structured/concept_matrix.md` — **概念矩阵**（动态键家族 × 性能，谁做了几篇；空格即空白。`python -m tools.paperdb --概念矩阵` 重建）
- `data/raw/<KEY>/parsed/full.md` — 解析出的全文 ｜ `data/curated/<KEY>/summary.html` — 中文精读
- `data/serving/vector_db/` — 向量库（2026-09-07 在 B 机实测 13906 块：粗层 10418 + **精层 2873** + SI 615，供 `tools/ask` 检索）
  ✅ **精层已补齐**：42 篇有 `parsed/full.md` 的全部在库；有 SI 原件的也全进了；同一篇两档并存 0 篇（精层入库时粗层自动退场）。（2026-09-06 前这里只有 276 块 —— 判重问错了问题，见踩坑 #126；代码当天修好并已在主力机跑过。）

## 语言约定与模型分工（别搞混）

**给用户看的用中文**（精读 HTML、问答答案）；**机器数据用原生英文**（结构化抽取、
图表数据 —— 用户本来就读英文文献，中间数据是给 LLM 用的）。

向量化 `bge-m3`（本地免费）· 其余环节走**路由表**（控制面板「① 通道 / ② 用途 / ③ 账本」，
`shared/kernel/config/routing.py`）：每个用途指定主用通道 + 模型 + 备用通道，
中转站（如阿里云优惠额度）当正式通道加进去即可。图表数字化**必须云端视觉模型**。
原则仍是**输出少的活上 pro，输出多的上 flash** —— 但注意 DeepSeek 的现状（2026-09-11 查证）：
flash 的正式名已是 `deepseek-flash`（旧名 `deepseek-v4-flash` 靠转发仍能用）；
**9 月 14 日起 `deepseek-v4-pro` 会被官方静默路由到 Flash 并按 Flash 计费**，V4.1 Pro 尚未发布。

## 运维现状（不用管，已自动化）

两个自启任务：`ZoteroLiteratureWatcher`（名字是历史遗留，跑的是**看门狗**：守文献库应用 8780、MCP 服务 8778、取全文浏览器 9333）、`OllamaService`。
**密钥存在系统凭据库**，硬盘上没有明文；统一走 `shared.kernel.config.get_key()`，
加载顺序：环境变量 → 系统凭据库 → `.env`。用户在**控制面板**里填写与切换。

用户的操作入口：**桌面「文献库」快捷方式**（文献库应用）与 **`launch/控制面板.bat`**（设置、密钥、运维）。人看的地图在 `README.md`。

## ⚠ 最高优先级：先看真实世界，别用记忆代替调研

架构准则【调研先行原则】（2026-08-09 立）。用户原话：
> **你下意识回答我的往往还是预训练的结果，我们还是要主动去看真实实时的世界是怎么样。**

<!-- AUTO:调研先行原则 开始 · 源在 docs/explain/架构准则_第一性原理.md，由 host/codegen/handover.py 抄过来，勿手改 -->

- 外部世界现状的断言（有无某功能、定价、限额、版本、行业惯例）→ **必须查**
- 具体数字 → 查到出处才说，查不到就明说查不到
- 外部 API 行为 → 真实调用实测，不信文档也不信记忆

**现场例证（这是本条真正起作用的部分，不许抽象掉）**：我曾断言「MineRU 的 token
通常两周过期」。查证后官方**根本没给任何天数** —— 那个「两周」是我编的，
一个听起来精确、实则无据的数字。

**自查方法**：说完一句判断，问自己「这是**刚查到的**，还是我**本来就『知道』的**？」
后者一律打问号。

**唯一停止判据**：这次调研能不能改变我接下来的做法？能就查，不能就别查。

<!-- AUTO:调研先行原则 结束 -->

→ 四步调研法见 `research-first` skill。

---

# 第二部分 · 开发约定（要改代码时看这里）

## 最高纲领

**先读 `docs/explain/架构准则_第一性原理.md`** —— 它定义整个系统怎么构筑：
原子模块 → 工作流 → 编排，以及「按稳定性决定自己做还是用现成」的选型判据。
**它是分级的**：每条带【事实】/【硬约束】/【启发式】标记，
**标着【启发式】的你可以推翻** —— 遇到反例有义务说出来并给证据，闷头照办才是违规。
（旧版 288 行的哲学与推导原文在 `架构准则_v1_历史存档.md`，已不生效，查「为什么」时用。）

## 核心归属（2026-09-07 立；2026-10-13 Zotero 移出平台）

**证据库是唯一的库。** 用户原话（09-13）：
> 数据库是单独的核心；文献文件的核心也不再是库里，是我们下文献的那个地方。

2026-10-13：「先把 Zotero 踢出体系，后面再单独做 Zotero 我想要的功能，现在对 Zotero 需求已经变了。」

- 文献 id **按 DOI 起**（`paths.paper_id_from_doi`：`doi_10.1021-acs.x`），唯一执行点是 `paths.check_key()`；
  **跨来源认同一篇靠 DOI**。2026-10-12 起 220 个老的 Zotero 编号目录已改名，7 篇没 DOI 的还是 8 位编号；
  **旧编号照样认得**（`catalog.resolve`，对照就是目录卡里的 `zotero_key` 属性）。
- **「有没有这篇」问证据库目录 `shared.kernel.catalog`**（零网络）。
- 正本在 `data/raw/<id>/`（`main.pdf` / `si.*` / `parsed/`），目录在 `curated/<id>/meta.json`。
  **「收一篇」= `getpdf.land()`：落正本 + 登记**。
- 精读 / 解析找 PDF 与 SI **只认本地正本**。有范文（公众号推文 `reference.md`）的，推文当正文精读、我们只补 SI（2026-09-15 用户定）。
- 精读由人在文献库应用里点（`host/app/runner.py`，一篇一篇排队，不回写任何地方）。
- 作者 / 通讯 / 单位 / 摘要索引在 `serving/oa_index.json`（OpenAlex 取一次，可重建）；研究团队名单 `state/teams.json`（人工查证，不可重建）。
- ⏸ **2026-09-27 起后台自动建库已停**（本机设置 `AUTO_BUILD=0`，用户定）：落地流水线、每日盯新刊取件都不跑；下面这条在开关打开时才生效。
- **落地即自动**（`host/ingest`）：正本一到，MineRU 解析 → 骨架 → 向量化自动做完，
  一分钱大模型的钱不花；之后模型就能 `library_outline` → `library_section` 自己读它。

**装一次才能跑**（换电脑/重装后必做）：`pip install -e . --no-deps`

## 五层与四条硬规则（`tests/test_architecture.py` 里的守卫会强制它们）

```
host  →  tools  →  shared.domain / shared.adapters  →  shared.kernel
```

**该往哪一层放，判据是「什么会让它需要改」**：`kernel` 几乎不会改（路径/配置/日志/
异常/参数/锁）· `domain` 只有我们自己想法变了才改（算法/格式/schema），
**且不许知道文件放在哪** · `adapters` 外部世界变了才改，**只有这一层能联网** ·
`tools` 需求一变就变 · `host` 平台自身的运维方式变了才改。

1. **下沉规则**：被 ≥2 个使用者用到才配住 `shared/`；只有 1 个用，搬进那个使用者里
2. **工具隔离**：`tools/*` 不许 import 别的 `tools/*` ——
   共用**下沉**到 shared、跨工具编排**上浮**到 host、或整个搬过去
3. **联网只在** `shared/adapters/`（这是「换掉 MineRU 只改一个文件」的全部保证）
4. **没人 import `host/`**；`host/` 可以 import 一切

**改任何 .py 之前先读 `code-redlines` skill**（七条强制规范 + 必备文件/必备文件准入 + 验证顺序）。

## 工具包的形状（`tools/<名>/`，七件缺一不可）

`tool.toml` · `__init__.py` · `cli.py` · `mcp.py` · `SKILL.md` · `README.md` · `tests/`
（另有 `selftest.py` · `INCIDENTS.md` · `prompts/` · `evals/`）。
`expose` 判据按**代价量级 + 可不可逆**分三档（2026-09-01 改，踩坑 #95）：
只读且便宜 → `tool`；只读数据 → `resource`；**全库作业 / 不可逆写 → `prompt`**。
其中「单次、便宜、可重来」的入口（问一次库 / 抽一篇 / 读一张图）可以逐个写进
`tool.toml` 的 `agent_tools` 白名单放开成 tool，但必须 `confirm=True`
（客户端每次弹窗且无「不再询问」）。**两道闸缺一不可，守卫双向查。**

⚠ **第三道闸（2026-09-10 加）：白名单本身也要准入。**
往 `agent_tools` 加一个名字，必须同时在 `tests/test_architecture.py` 的
`AGENT_TOOLS_APPROVED` 里登记**并写明理由**，否则守卫变红。
第二处存在的意义就是逼人把「为什么它是单次/便宜/可重来」写成一句话。
`discover` / `direction` / 整批 `getpdf` / 整篇 `deepread` 列在
`HUMAN_ONLY` 里，**永远只给人点**。

⚠ 而且要知道：**弹窗那道闸不是硬的。** `confirm` 是 Claude Code 专有标记，
换个客户端（Antigravity）会被直接忽略 —— 2026-09-10 外部 agent 批量精读 10 篇，
全程无人确认，余额从 2.48 掉到 1.04 元。真正硬的是服务端的当日额度闸
（`shared/kernel/budget.py`，在控制面板设 `DAILY_LLM_CALLS` / `DAILY_LLM_TOKENS`）。
**加白名单之前先问：如果客户端不弹窗，这件事我还敢让它自己做吗？**

提示词进 `prompts/<名>_v<N>.txt`，**只增不改**，版本在 `tool.toml` 里声明。

## `.claude/` 全部是生成物，**手写即违规**（有守卫）

改源之后跑生成器：

```bash
python host/codegen/skills.py       # tools/*/SKILL.md + docs/howto/{skills,rules}/ → .claude/
python host/codegen/incidents.py    # tools/*/INCIDENTS.md → docs/incidents/README.md
python host/codegen/handover.py     # → HANDOVER.md + 本文件的结构树 + docs/reference/系统认识_各块机制与弱点.md
```

## 验证自主性

**自主做**：只读/验证类命令、A/B 对比、单篇验证、读脚本读数据 → 跑完直接报结果。
**先问用户**：全库重抽（花钱）、覆盖/删除数据、
方向性抉择（改 schema、换技术路线 —— 那是用户的领域判断）。

## 日志纪律（每次改动都要）

- 技术发现/踩坑 → 当场追加 `docs/incidents/踩坑记录.md`（编号 + 现象/根因/解法）；
  工具特有的同时写进 `tools/<t>/INCIDENTS.md`。
  **新增前先 `grep "^## " 看真实最大号**，别凭印象编（踩坑 #91：编号撞过车）
- 改代码/删数据/运维 → 当场记 `docs/变更记录.md`
- 需要改架构但还没做 → 记 `docs/待办与需求.md`
- 写中文用 Python `io.open(...encoding='utf-8')` 追加，避开 PowerShell 的 GBK 乱码
- **每个改动 Git commit**

## 已知环境坑（速记，细节见 `troubleshoot` skill）

PowerShell 控制台中文乱码 → **先用 Read 工具确认真实内容**，再判断是显示还是数据。
**MCP 调用约 60 秒超时** → 精读、全库抽取、大模型读图会超时但后台继续，发起后轮询文件。
文档：`docs/explain/` 为什么 · `docs/howto/` 怎么做 · `docs/reference/` 事实 ·
`docs/incidents/` 坑 · `docs/变更记录.md` · `docs/待办与需求.md`
· `docs/项目结构导览.md`（给人的结构地图，含**还没处理好的清单**）
