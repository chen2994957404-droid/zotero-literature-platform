# 交接文件 · 我们做到哪了

> **本文件由 `平台管理/交接.py` 自动生成，不要手改** —— 手写的文档一定会过时。
> 生成时间：2026-08-26 21:59

新对话请按这个顺序读：本文件 → `CLAUDE.md` → 需要动哪块就读那个文件夹的 `CLAUDE.md`。

## 目录结构（**不要去 glob 根目录**，数据目录有 3000+ 文件会淹掉你）

```
MCP服务/ （3 个脚本）
    mcp_stdio.py、selftest.py、zotero_server.py
adapters/  ← 外接口：唯一允许联网/用第三方库的一环（9 块）
    embed、evalset、llm_client、openalex、pdf_parse、sciverse、snowball、vectordb、zotero_client
core/  ← 内核：谁都依赖它，它不依赖任何人（8 块）
    cli、config、proc_lock、subproc、errors.py、log.py、paths.py、role.py
docs/                    ← 文档（15 份）
domain/  ← 纯逻辑：不联网、不知道文件放在哪（2 块）
    figure_crop、si_filter
pipelines/  ← 编排：把上面三者按顺序组合成能力（4 块）
    chart_digitize、lib_match、paper_discovery、query_expand
tests/ （6 个脚本）
    test_adapters_vectordb.py、test_architecture.py、test_core_log_errors.py、test_core_paths.py、test_core_role.py、test_no_undefined_names.py
平台管理/ （6 个脚本）
    health_check.py、panel.py、panel_launch.py、交接.py、更新平台.py、诊断报告.py
库内问答/ （4 个脚本）
    ask.py、ask_world.py、vectorize.py、vectorize_library.py
库房维护/ （7 个脚本）
    auto_sync.py、autotag.py、backfill_meta.py、delete_junk.py、list_junk.py、tag_to_nested.py、zotero_rename.py
归档_旧版本/ （2 个脚本）
    build_deepread_workflow.py、watcher.py
找新文献/ （7 个脚本）
    brainstorm.py、collect.py、discover.py、find_papers.py、import_by_doi.py、search_global.py、zotero_add_thesis.py
数据抽取/ （4 个脚本）
    extract_batch.py、extract_library.py、extract_structured.py、filter_domain.py
文献精读/ （12 个脚本）
    deepread_batch.py、deepread_v4.py、merge_summary.py、mineru_parse.py、refresh_summary_file.py、rerun_pro.py、si_batch.py、si_deepread.py…

根目录文件：CLAUDE.md、LICENSE、README.md、pyproject.toml、requirements.txt、控制面板.bat、更新平台.bat、精读监听.bat、诊断报告.bat

（workflow_data/ 是数据目录，3000+ 文件，**不要去 glob 它**）
```

## 现在健康吗

`结果：12 通过，4 警告，1 失败`

- [WARN] 密钥存放: 凭据库可用（WinVaultKeyring），但一个密钥都没存 —— 5 个待填，请在控制面板里配置
- [FAIL] 配置加载: 缺少: ['DEEPSEEK_KEY', 'ZOTERO_API_KEY', 'MINERU_TOKEN']
- [WARN] Ollama 服务: Ollama 未跑（问答/向量化会失败）
- [WARN] 公理件自测: 15/18 自测通过（共 19 个公理件）；跳过慢测试 ['chart_digitize']（--full 可跑）；失败: ['embed', 'llm_client', 'query_expand']
- [WARN] 数据资产: library 0 篇 / structured 0 条 / 向量库在 —— 编程端没有金样本，纯逻辑改动无法做回归验证；建议从主力机拷 2~3 篇的 parsed/ 过来

## 👉 下一步该做什么

- **先修体检报的问题**（见上一节），其余都往后放
- **攒精读评测集**：还差「好」3 篇、「差」3 篇。用户在 Zotero 打「读完」标签 → 控制面板「精读评价」里评。评够后即可做「自动质量分」校准，让系统自己发现精读退化。

## 最近做了什么（git 提交，新到旧）

- `08-26` 两台机器分工落地：机器角色守卫 + 主力机操作面
- `08-26` 重构阶段2：拆开公理层为四环 + 消灭三处重复实现 + 修一个隐藏 bug
- `08-26` 重构阶段1完成：core/log（统一日志+轮转）+ core/errors（异常分类）
- `08-26` 重构阶段0收尾：体检分离线/实测两档 + 文档同步 + 消灭第4份重复清单
- `08-26` 重构阶段0+1：项目装成 Python 包 + 数据契约收进 core/paths
- `08-26` 记录本次排查：踩坑 #43~#47 + 变更记录 + 刷新交接文件
- `08-26` 控制面板加 CSRF 防护；清掉 watcher 死代码；两处小修
- `08-26` 打通配置管道：面板改地址终于生效；体检补上守红线#3的检查项
- `08-26` 修两个后台服务的真 bug：MCP 中文乱码 + 单实例锁失效
- `08-25` MCP服务/CLAUDE.md 补充 Codex/Claude Code 接入示例（查证官方文档，绝对路径不依赖工作目录）

## 精读质量评测集

- 已评价 **0** 篇（好 0 / 差 0）
- ⏳ 还不够做校准（需好、差各 ≥3 篇）。用户在 Zotero 打「读完」标签 → 控制面板「精读评价」里评。

## 项目组成

| 文件夹 | 脚本数 | 是什么 |
|---|---|---|
| `MCP服务` | 3 | **平台对外的 MCP 接口层**（宪法里的「界面层」）：把平台已有的能力包成 |
| `pipelines` | 1 | **本身不解决任何原子问题，只负责「按什么顺序调用谁」的代码。** |
| `平台管理` | 6 | 平台自己的仪表盘和体检工具 —— **用户与整个系统的交互入口**。 |
| `库内问答` | 4 | 让用户能用大白话问自己的文献库：「我库里关于 B–N 配位有什么？」 |
| `库房维护` | 7 | 打理 Zotero 库本身：标签、元数据、命名、去重、同步。 |
| `找新文献` | 7 | 帮用户往文献库里**补新文献**：按主题去外部检索、标出哪些库里已有、 |
| `数据抽取` | 4 | 把每篇文献的关键信息抽成**结构化字段**（材料体系、动态键类型、合成条件、性能数值、 |
| `文献精读` | 12 | 把一篇文献（PDF）变成一份中文图文精读报告，并自动回写到用户的 Zotero 里。 |

**积木层 `modules/`（19 块）**：`cli`、`config`、`proc_lock`、`subproc`、`figure_crop`、`si_filter`、`embed`、`evalset`、`llm_client`、`openalex`、`pdf_parse`、`sciverse`、`snowball`、`vectordb`、`zotero_client`、`chart_digitize`、`lib_match`、`paper_discovery`、`query_expand`

## 待办（可能已过时，动手前先核实）

- 工单列表
- watcher 重复实例（面板发现，2026-08-06）
- 2026-08-26 · 架构重构 v2 的后续阶段

## 最近踩的坑（全文见 `docs/踩坑记录.md`）

- 踩坑 #46：面板存 `ZOTERO_API_HOST`，积木读 `ZOTERO_LOCAL_API` —— 键名对不上，改了不生效
- 踩坑 #47：「只绑 127.0.0.1」挡得住别的机器，挡不住你自己浏览器里的网页
- 踩坑 #48：logging 的 Logger 是全局的，同名再取一次会把 handler 挂两遍（2026-08-26）
- 踩坑 #49：「模块能 import 成功」远不等于「代码没问题」（2026-08-26）
- 踩坑 #50：部署 ≠ 把文件换掉 —— 常驻进程不重启就一直跑旧代码（2026-08-26）

## 想深入时读哪份（**这两份是时间正序的长文件，用 tail 读末尾，别从头读**）

- `docs/踩坑记录.md`（65 KB） — 所有踩过的坑，含根因与解法
- `docs/变更记录.md`（113 KB） — 每次改动的来龙去脉
- `docs/架构宪法_第一性原理.md`（17 KB） — 最高纲领：三条铁律 + 零号/首要判据
- `<某文件夹>/CLAUDE.md` — 那一块的完整说明书，改哪块就读哪份

## 铁律提醒

- **【零号判据】先看真实世界，别用记忆代替调研。**涉及外部现状/具体数字/API 行为，必须查、必须测。
- 改完**先跑体检再重启服务**：`python 平台管理/health_check.py`
- 花钱、不可逆、影响 Zotero 库的操作，**先问用户**。
- 每个改动记 `docs/变更记录.md`，踩坑记 `docs/踩坑记录.md`，并 git commit。
