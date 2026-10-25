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
    explain/（3）、howto/（2）、reference/（5）、incidents/（2）  ← 为什么 / 怎么做 / 事实 / 坑
host/  ← 平台自身：让平台活着的东西（没人 import 它）（8 块）
    app、codegen、deploy、doctor、ingest、mcp、panel、watcher
launch/  ← 给人双击的入口（常用 4 个；不常用/ 里 3 个备用与开发用）
    取全文用的浏览器.bat、控制面板.bat、设置与密钥.bat、运行与日志.bat
    不常用/：更新平台.bat、诊断报告.bat、连上文献平台（Antigravity用）.bat
outputs/  ← 外部 agent 的产物 / 草稿，不进版本库
scratch/  ← 外部 agent 的产物 / 草稿，不进版本库
shared/  ← 共用件：被 ≥2 个工具用到才允许住这里
    kernel/  ← 基础设施：谁都依赖它，它不依赖任何人（10 块）
        cli、config、subproc、catalog.py、errors.py、heartbeat.py、jobs.py、log.py、paths.py、role.py
    domain/  ← 纯逻辑：不联网、不知道文件放在哪（1 块）
        outline
    adapters/  ← 外接口：唯一允许联网/用第三方库的一环（15 块）
        ccdc、chemdb、cnki、crossref、embed、jcr、openalex、pdf_fetch、pdf_parse、polyinfo、pubchem、scopus、tansoole、unpaywall、vectordb
tests/ （4 个脚本）
    test_architecture.py、test_no_undefined_names.py、test_principles.py、test_types.py
toolbox/ （0 个脚本）
tools/  ← 工具包：一个工具 = 一个自包含的包（2 块）
    getpdf、library

根目录文件：AGENTS.md、BA_TRIS_DMAEMA_三元共聚20g小试实验指南.md、CLAUDE.md、LICENSE、README.md、REBUILD.md、conftest.py、pyproject.toml、pyrightconfig.json、requirements.txt、各部分的关系.md

（data/ 是数据目录（五层），3000+ 文件，**不要去 glob 它**）
```

**可枚举的模块 21 个**（`tools/` 工具包 + `shared/` 共用件，每个都有 `__init__.py` 与 `selftest.py`）

进度、健康状况、下一步做什么 → 见 `HANDOVER.md`

<!-- AUTO:结构 结束 -->

## 📌 新对话第一件事：读 `HANDOVER.md`（**别先 glob 根目录**）

**出了问题、或要动一块之前**：读 `docs/reference/系统认识_各块机制与弱点.md`（生成物）——
每块靠什么外部东西、踩过哪些坑、最近改过什么，按块聚合。知道它怎么做的，才猜得到它会坏在哪。

上面那棵树就是全部结构，不必再扫 —— `data/` 有 3000+ 个数据文件，
glob 根目录会直接淹掉上下文（实测：前 100 个结果全是解析出来的图片）。

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
| `two-machines` | 部署 / 连 B / 起常驻服务（连机器的机械细节在**全局**技能 `remote-machine`，源在 `toolbox/remote-machine/`）|
| `library` · `getpdf` 各一份 | 要用某个工具时（含**什么时候别用我**）|

---

# 第一部分 · 能力速查（用户提科研需求时看这里）

**2026-10-23 用户定的形状**：平台只管两样 —— **原始数据**（正文 PDF + SI）和**加工到最适合 agent 读的数据**
（解析全文、骨架、整图、向量库），给 **Claude Science** 用。读文献、找新文献、比数值、读曲线都交给 Claude Science 自己做；
中文精读、结构化抽取、数值库、找文献 / 盯新刊 / 方向地图、问库问答这些已整套删掉（代码在 git 历史里）。

| 用户说 | 你怎么做 |
|--------|---------|
| 「库里有没有 XX 这篇」「手上有哪些文献」| `python -m tools.library 库 XX`（零网络、秒回；结果标出每篇有正文 / SI / 已解析没有）|
| 「按 DOI / 标题词 / 通讯作者 / 团队 / 年份 / 期刊找」| `python -m tools.library 检索 …`（他自己用的是文献库应用里的检索页，同一套）|
| 「某个研究团队有哪些文章」| `python -m tools.library 团队 XX`（名单在 `data/state/teams.json`，人工查证）|
| 「把这几篇（DOI）收进来」| `python -m tools.getpdf DOI …`（借真实浏览器取正文 + SI，落地后自动解析 → 骨架 → 向量化）|
| 「读某篇 / 讲了什么」「全世界有没有人做过」「比数值、读曲线」| 交给 **Claude Science**（它连 `/science` 接口：`library_*` 读库、`paper_fulltext` 取全文、各网页库）|

## 现成数据资产

- `data/raw/<id>/main.pdf` · `si.*` — 原件正本
- `data/raw/<id>/parsed/full.md` · `si_parsed/full.md` — 解析出的全文（含 `images/`、`layout.json`）
- `data/curated/<id>/meta.json` · `outline.json` · `figures/` — 目录卡、骨架（章节菜单）、按版面裁好的整图（可重裁）
- `data/serving/vector_db/` — 向量库（本地 bge-m3），供 `library_retrieve` 按意思找段落
- `data/serving/oa_index.json` · `data/state/teams.json` · `topics.db` — 作者/摘要索引（可重建）、研究团队名单（人工，不可重建）、专题

## 模型

向量化 `bge-m3`（本机 Ollama，免费；本机设置 `OLLAMA_HOST`，模型 `EMBED_MODEL` 默认 bge-m3，换模型 = 向量库重建）。
平台自己**不调生成式大模型**：2026-10-24 大模型的通道 / 用途 / 账本（`routing`、`budget`、`llm_client`）整套撤掉了，
控制面板里只剩 MineRU 与 OpenAlex 两把密钥。以后真要接回来，额度闸要跟着一起回来（见下面「第三道闸」那段）。

## 运维现状（不用管，已自动化）

两个自启任务：`LiteraturePlatformWatchdog`（**看门狗**：守文献库应用 8780、MCP 服务 8778、取全文浏览器 9333）、`OllamaService`。
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
- 解析找 PDF 与 SI **只认本地正本**。
- 作者 / 通讯 / 单位 / 摘要索引在 `serving/oa_index.json`（OpenAlex 取一次，可重建）；研究团队名单 `state/teams.json`（人工查证，不可重建）。
- ⏸ **2026-09-27 起后台自动建库已停**（本机设置 `AUTO_BUILD=0`，用户定）：落地流水线不常驻；下面这条在开关打开时才生效（关着时可手动 `python -m host.ingest` 清积压）。
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
整批 `getpdf` 列在 `HUMAN_ONLY` 里，**永远只给人点**。

⚠ 而且要知道：**弹窗那道闸不是硬的。** `confirm` 是 Claude Code 专有标记，
换个客户端（Antigravity）会被直接忽略 —— 2026-09-10 外部 agent 批量精读 10 篇（精读已于 2026-10-23 删掉），
全程无人确认，余额从 2.48 掉到 1.04 元。所以硬闸必须在服务端：现在放开的两个入口
（取一篇 / 一次最多 25 篇全文）由 `/science` 服务端强制间隔与上限；原来管花钱的当日额度闸 `budget.py`
随大模型一起撤了 —— **以后再接任何花钱的调用，先把服务端额度闸接回来**。
**加白名单之前先问：如果客户端不弹窗，这件事我还敢让它自己做吗？**

提示词（以后若有）进 `prompts/<名>_v<N>.txt`，**只增不改**（读取器 2026-10-24 随最后一个用户删了，git 历史里有）。

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
**MCP 调用约 60 秒超时** → 取全文这类慢活会超时但后台继续，发起后轮询（`fulltext_status`）。
文档：`docs/explain/` 为什么 · `docs/howto/` 怎么做 · `docs/reference/` 事实 ·
`docs/incidents/` 坑 · `docs/变更记录.md` · `docs/待办与需求.md`
· `docs/项目结构导览.md`（给人的结构地图，含**还没处理好的清单**）
