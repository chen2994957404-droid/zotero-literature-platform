# 文献自动化科研平台 · 给所有 agent 的正本

围绕 Zotero 的文献科研平台。用户是材料方向研究者（聚硼硅氧烷 / 动态键弹性体），
**不懂编程**。给他看的一律用中文大白话，别讲技术细节。

**这份是唯一入口。** 帮他干活看【第一部分】，改代码看【第二部分】。
`CLAUDE.md` 只是指向这里的一行。

<!-- AUTO:结构 开始 · 由 host/codegen/handover.py 生成，勿手改 -->

## 项目结构（自动同步，**不要 glob 根目录**）

> `data/` 有 3000+ 个数据文件，glob 根目录会直接淹掉你的上下文。
> 下面这棵树就是全部结构，不必再去扫。

```
docs/  ← 跨工具的档案（另有 2 份日志直接躺在下面）
    explain/（5）、howto/（3）、reference/（5）、incidents/（2）  ← 为什么 / 怎么做 / 事实 / 坑
host/  ← 平台自身：让平台活着的东西（没人 import 它）（7 块）
    autosync、codegen、deploy、doctor、mcp、panel、watcher
launch/  ← 给人双击的入口（7 个）
    控制面板.bat、更新平台.bat、比一比两个模型.bat、精读监听.bat、诊断报告.bat、重抽缺SI的文献.bat、重跑精读PRO.bat
shared/  ← 共用件：被 ≥2 个工具用到才允许住这里
    kernel/  ← 基础设施：谁都依赖它，它不依赖任何人（12 块）
        cli、config、proc_lock、prompts、subproc、errors.py、heartbeat.py、jobs.py、log.py、mcp_prompt.py、paths.py、role.py
    domain/  ← 纯逻辑：不联网、不知道文件放在哪（2 块）
        figure_crop、schema
    adapters/  ← 外接口：唯一允许联网/用第三方库的一环（11 块）
        crossref、embed、llm_client、openalex、pdf_parse、query_expand、sciverse、snowball、vectordb、wechat_seed、zotero_client
specs/ （0 个脚本）
tests/ （2 个脚本）
    test_architecture.py、test_no_undefined_names.py
tools/  ← 工具切片：一个工具 = 一个自包含的包（10 块）
    ask、askworld、curate、deepread、digitize、direction、discover、extract、library、paperdb

根目录文件：AGENTS.md、CLAUDE.md、LICENSE、README.md、REBUILD.md、pyproject.toml、requirements.txt

（data/ 是数据目录（五层），3000+ 文件，**不要去 glob 它**）
```

**可枚举的块 28 个**（`tools/` 工具切片 + `shared/` 共用件，每个都有 `__init__.py` 与 `selftest.py`）

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
| `code-redlines` | **要动任何 .py 之前**（七条红线 + 四条硬规则 + 验证顺序）|
| `research-first` | 要做新东西、选技术路线、或要断言外部世界现状 |
| `two-machines` | 写 Zotero / 部署 / 连 B / 起常驻服务 |
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
- `data/serving/vector_db/` — 向量库（9105 块，供 `tools/ask` 检索）

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

宪法【零号判据】（2026-08-09 立）。用户原话：
> **你下意识回答我的往往还是预训练的结果，我们还是要主动去看真实实时的世界是怎么样。**

外部世界现状（有无某功能、定价、限额、惯例）**必须查**；具体数字查到出处才说；
外部 API 行为**真实调用实测**。**听起来很具体的数字最像事实，也最可能是编的** ——
说完一句判断先自问：这是刚查到的，还是我本来就「知道」的？

**停止判据**：这次调研能不能改变我接下来的做法？能就查，不能就别查。
→ 四步调研法见 `research-first` skill。

---

# 第二部分 · 开发约定（要改代码时看这里）

## 最高纲领

**先读 `docs/explain/架构宪法_第一性原理.md`** —— 它定义整个系统怎么构筑：
公理→定理→组合，三条铁律，以及「按稳定性决定自己做还是用现成」的首要判据。

**装一次才能跑**（换电脑/重装后必做）：`pip install -e . --no-deps`

## 五层与四条硬规则（守卫强制，`tests/test_architecture.py` 24 条）

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

**改任何 .py 之前先读 `code-redlines` skill**（七条红线 + 三件套/七件套准入 + 验证顺序）。

## 工具切片的形状（`tools/<名>/`，七件缺一不可）

`tool.toml` · `__init__.py` · `cli.py` · `mcp.py` · `SKILL.md` · `README.md` · `tests/`
（另有 `selftest.py` · `INCIDENTS.md` · `prompts/` · `evals/`）。
`expose` 判据：**只读且便宜 → `tool`；只读数据 → `resource`；花钱或有副作用 → `prompt`**
（花钱的注册成 `tool` 等于把钱包交给模型，踩坑 #86，守卫会拦）。
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
