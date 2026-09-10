# literature-platform · 给所有 agent 的正本

文献自动化科研平台，**核心是证据库**，Zotero 是最重要的来源 + 精读成果的展示面。
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
docs/  ← 跨工具的档案（另有 3 份日志直接躺在下面）
    explain/（7）、howto/（3）、reference/（6）、incidents/（2）  ← 为什么 / 怎么做 / 事实 / 坑
host/  ← 平台自身：让平台活着的东西（没人 import 它）（8 块）
    autosync、codegen、deploy、doctor、mcp、panel、watcher、wechat_import
launch/  ← 给人双击的入口（10 个）
    取全文用的浏览器.bat、导入公众号精读.bat、控制面板.bat、更新平台.bat、比一比两个模型.bat、精读监听.bat、诊断报告.bat、连上文献平台（Antigravity用）.bat、重抽缺SI的文献.bat、重跑精读PRO.bat
scratch/ （0 个脚本）
shared/  ← 共用件：被 ≥2 个工具用到才允许住这里
    kernel/  ← 基础设施：谁都依赖它，它不依赖任何人（13 块）
        cli、config、proc_lock、prompts、subproc、budget.py、errors.py、heartbeat.py、jobs.py、log.py、mcp_prompt.py、paths.py、role.py
    domain/  ← 纯逻辑：不联网、不知道文件放在哪（3 块）
        figure_crop、libmatch、schema
    adapters/  ← 外接口：唯一允许联网/用第三方库的一环（12 块）
        crossref、embed、llm_client、openalex、pdf_fetch、pdf_parse、query_expand、sciverse、snowball、vectordb、wechat_seed、zotero_client
specs/ （0 个脚本）
tests/ （4 个脚本）
    test_architecture.py、test_budget.py、test_no_undefined_names.py、test_principles.py
toolbox/ （0 个脚本）
tools/  ← 工具包：一个工具 = 一个自包含的包（12 块）
    ask、askworld、curate、deepread、digitize、direction、discover、extract、getpdf、library、litsearch、paperdb

根目录文件：AGENTS.md、CLAUDE.md、LICENSE、README.md、REBUILD.md、pyproject.toml、requirements.txt、各部分的关系.md

（data/ 是数据目录（五层），3000+ 文件，**不要去 glob 它**）
```

**可枚举的模块 32 个**（`tools/` 工具包 + `shared/` 共用件，每个都有 `__init__.py` 与 `selftest.py`）

进度、健康状况、下一步做什么 → 见 `HANDOVER.md`

<!-- AUTO:结构 结束 -->

## 📌 新对话第一件事：读 `HANDOVER.md`（**别先 glob 根目录**）

上面那棵树就是全部结构，不必再扫 —— `data/` 有 3000+ 个数据文件，
glob 根目录会直接淹掉上下文（实测：前 100 个结果全是精读图片）。

`HANDOVER.md` 由 `python host/codegen/handover.py` 生成，全部抓自系统真实状态：
当前健康状况、最近十次改动、评测集进展、待办、最近踩的坑。
**本文件说「这个项目是什么」，交接文件说「我们做到哪了」，两者缺一不可。**

## ⚠ 两台机器 —— 你在 A 机（编程端）

**A 机 = 改代码的唯一入口；B 机 = 主力机，数据与服务的权威副本，没有 Claude Code。**
A 机默认不写 Zotero、不跑常驻服务、不跑花钱的批量作业 ——
但 2026-08-27 起 A 机多了独立的测试 Zotero 账号（`ROLE=test`），这一档允许写、允许跑。

涉及写 Zotero / 部署到 B / 连 B 排查 / 起常驻服务 → **读 `two-machines` skill**。

## 🧰 按需加载的 skill（`.claude/skills/`，全部由生成器产出）

本文件只留「每次会话都要知道」的。下面这些**按需**读，别凭记忆作答：

| skill | 什么时候读 |
|---|---|
| `troubleshoot` | 报错 / 卡住 / 没反应 / 数字不对 / 明明改了却没变 |
| `code-redlines` | **要动任何 .py 之前**（七条强制规范 + 四条硬规则 + 验证顺序）|
| `research-first` | 要做新东西、选技术路线、或要断言外部世界现状 |
| `two-machines` | 写 Zotero / 部署 / 连 B / 起常驻服务（连机器的机械细节在**全局**技能 `remote-machine`，源在 `toolbox/remote-machine/`）|
| 十个工具各一份 | 要用某个工具时（含**什么时候别用我**）|

---

# 第一部分 · 能力速查（用户提科研需求时看这里）

| 用户说 | 你怎么做 |
|--------|---------|
| 「库里有没有 XX 这篇」「最近加了什么」「有哪些标签」| `python -m tools.library search XX`（只读、免费、秒回）|
| 「我库里关于 XX 有什么？」| `python -m tools.ask "问题"`（RAG，中文答 + 附来源。**只是找某篇在不在，用上面那条更便宜**）|
| 「帮我找 XX 方向的文献」| `python -m tools.discover "关键词"`（拆检索式 + 雪球 + 按「跟他多相关」排序）|
| 「帮我横向比较 XX」「这方向有什么空白」| 读 `data/serving/structured/compare.md`；PBS 方向另有 `compare_PBS.md` |
| 「精读某篇文献」| 让他在 Zotero 打「待处理」标签。**状态机自动判断**：只有正文→正文精读；有 SI→连 SI 一起→全文精读；已精读的只补缺的。服务已开机自启 |
| 「把某批文献的数据抽出来」| `python -m tools.extract KEY1 KEY2 --parse` |
| 「拉伸强度超过 10 MPa 的有哪些」| `python -m tools.paperdb --find ...`（能比大小的数值库）|
| 「全世界有没有人做过 XX」| `python -m tools.askworld "问题"`（Sciverse 取原文片段，**带出处**）|
| 「把论文图里的曲线变成数据」| `python -m tools.digitize 图片路径`，**必须用云端大模型**（本地 7B 会编假数据）|
| 「帮我想想研究方向」| 读 compare 表找「机理 × 性能」的空白格，或 `python -m tools.direction` |
| 「库里好像有重复的 / 标签乱了」| `python -m tools.curate`（打标签 / 改名 / 去重 / 同步）|

## 现成数据资产

- `data/serving/structured/compare.md` — 横向对比表（2026-08-28 实测 175 条：39 精层 + 136 粗层）
- `data/serving/structured/compare_reviews.md` · `compare_PBS.md` — 综述单列 · PBS 精层子表（10 篇）
- `data/raw/<KEY>/parsed/full.md` — 解析出的全文 ｜ `data/curated/<KEY>/summary.html` — 中文精读
- `data/serving/vector_db/` — 向量库（2026-09-07 在 B 机实测 13906 块：粗层 10418 + **精层 2873** + SI 615，供 `tools/ask` 检索）
  ✅ **精层已补齐**：42 篇有 `parsed/full.md` 的全部在库；有 SI 原件的也全进了；同一篇两档并存 0 篇（精层入库时粗层自动退场）。（2026-09-06 前这里只有 276 块 —— 判重问错了问题，见踩坑 #126；代码当天修好并已在主力机跑过。）

## 语言约定与模型分工（别搞混）

**给用户看的用中文**（精读 HTML、问答答案）；**机器数据用原生英文**（结构化抽取、
图表数据 —— 用户本来就读英文文献，中间数据是给 LLM 用的）。

向量化 `bge-m3`（本地免费）· 结构化抽取 `deepseek-v4-pro` · 精读 `deepseek-v4-flash` ·
图表数字化**必须云端大模型**。原则：**输出少的活上 pro，输出多的上 flash**。

## 运维现状（不用管，已自动化）

两个自启任务：`ZoteroLiteratureWatcher`（打「待处理」标签即自动精读）、`OllamaService`。
**密钥存在系统凭据库**，硬盘上没有明文；统一走 `shared.kernel.config.get_key()`，
加载顺序：环境变量 → 系统凭据库 → `.env`。用户在**控制面板**里填写与切换。

用户的操作入口是 **`launch/控制面板.bat`**（本地网页）。人看的地图在 `README.md`。

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

## 核心归属（2026-09-07 用户拍板，架构准则第四节）

**核心是「证据库」，Zotero 是它最重要的来源 + 精读成果的展示面，不是核心。**

- 文献的身份证**与来源无关**：Zotero 编号 / OpenAlex id / 由 DOI 生成的 id 都合法，
  唯一执行点是 `paths.check_key()`；「这篇在不在他自己库里」用 `paths.is_zotero_key()` 问；
  **跨来源认同一篇靠 DOI**。
- PDF 与全文的正本在 `data/raw/`；**推进 Zotero 的只是给人看的副本**。
- 数据库的写入口只有一条：B 机上的流水线。打标签 = 投稿，不是直接写库。

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
只读且便宜 → `tool`；只读数据 → `resource`；**全库作业 / 不可逆写 Zotero → `prompt`**。
其中「单次、便宜、可重来」的入口（问一次库 / 抽一篇 / 读一张图）可以逐个写进
`tool.toml` 的 `agent_tools` 白名单放开成 tool，但必须 `confirm=True`
（客户端每次弹窗且无「不再询问」）。**两道闸缺一不可，守卫双向查。**

⚠ **第三道闸（2026-09-10 加）：白名单本身也要准入。**
往 `agent_tools` 加一个名字，必须同时在 `tests/test_architecture.py` 的
`AGENT_TOOLS_APPROVED` 里登记**并写明理由**，否则守卫变红。
第二处存在的意义就是逼人把「为什么它是单次/便宜/可重来」写成一句话。
`curate` / `discover` / `direction` / 整批 `getpdf` / 整篇 `deepread` 列在
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
python host/codegen/handover.py     # → HANDOVER.md + 本文件的结构树
```

## 验证自主性

**自主做**：只读/验证类命令、A/B 对比、单篇验证、读脚本读数据 → 跑完直接报结果。
**先问用户**：全库重抽（花钱）、覆盖/删除数据、写真实 Zotero 库、
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
