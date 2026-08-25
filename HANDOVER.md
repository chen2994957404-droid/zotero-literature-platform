# 交接文件 · 我们做到哪了

> **本文件由 `平台管理/交接.py` 自动生成，不要手改** —— 手写的文档一定会过时。
> 生成时间：2026-08-25 15:46

新对话请按这个顺序读：本文件 → `CLAUDE.md` → 需要动哪块就读那个文件夹的 `CLAUDE.md`。

## 目录结构（**不要去 glob 根目录**，数据目录有 3000+ 文件会淹掉你）

```
MCP服务/ （3 个脚本）
    mcp_stdio.py、selftest.py、zotero_server.py
docs/                    ← 文档（13 份）
modules/                 ← 积木层（17 块）
    chart_digitize、cli、config、embed、evalset、figure_crop、lib_match、llm_client、paper_discovery、pdf_parse、proc_lock、query_expand、sciverse、si_filter、snowball、subproc、zotero_client
平台管理/ （4 个脚本）
    health_check.py、panel.py、panel_launch.py、交接.py
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

根目录文件：CLAUDE.md、LICENSE、README.md、requirements.txt、控制面板.bat、精读监听.bat

（workflow_data/ 是数据目录，3000+ 文件，**不要去 glob 它**）
```

## 现在健康吗

`结果：13 通过，0 警告，0 失败`

## 👉 下一步该做什么

- **攒精读评测集**：还差「好」3 篇、「差」3 篇。用户在 Zotero 打「读完」标签 → 控制面板「精读评价」里评。评够后即可做「自动质量分」校准，让系统自己发现精读退化。

## 最近做了什么（git 提交，新到旧）

- `08-25` 控制面板.bat 移除探针；记录计划任务实况更正+ControlPanel任务注册
- `08-25` 面板改控制台python启动+新建精读监听.bat(看门狗)；记录误杀watcher教训(踩坑#42)
- `08-25` 控制面板启动器：捕获pythonw静默报错到panel_launch.log，排查打不开问题
- `08-25` 修 llm_client 本地聊天：模型名走config(.env OLLAMA_MODEL)+关qwen3.5思考，自测3/3过（踩坑#41）
- `08-24` 记录：双机协作搭通（主仓库 chen2994957404-droid + 协作者推送）
- `08-24` README 增加两机协作说明（主仓库 chen2994957404-droid + 协作者工作流）
- `08-24` 记录：本机 Zotero 验证通过（zotero_client 3/3、体检 Zotero OK）
- `08-23` 交接文件刷新（含框架化两步提交）
- `08-23` 框架化批量迁移：36个脚本统一标准模板+modules/cli+modules/config（体检与基线一致）
- `08-23` 框架化验证闭环：cli pos() 修复(选项值误当位置参数)+自测/实跑/体检/交接全过；本机装好 Python 3.13.15

## 精读质量评测集

- 已评价 **0** 篇（好 0 / 差 0）
- ⏳ 还不够做校准（需好、差各 ≥3 篇）。用户在 Zotero 打「读完」标签 → 控制面板「精读评价」里评。

## 项目组成

| 文件夹 | 脚本数 | 是什么 |
|---|---|---|
| `MCP服务` | 3 | **平台对外的 MCP 接口层**（宪法里的「界面层」）：把平台已有的能力包成 |
| `平台管理` | 4 | 平台自己的仪表盘和体检工具 —— **用户与整个系统的交互入口**。 |
| `库内问答` | 4 | 让用户能用大白话问自己的文献库：「我库里关于 B–N 配位有什么？」 |
| `库房维护` | 7 | 打理 Zotero 库本身：标签、元数据、命名、去重、同步。 |
| `找新文献` | 7 | 帮用户往文献库里**补新文献**：按主题去外部检索、标出哪些库里已有、 |
| `数据抽取` | 4 | 把每篇文献的关键信息抽成**结构化字段**（材料体系、动态键类型、合成条件、性能数值、 |
| `文献精读` | 12 | 把一篇文献（PDF）变成一份中文图文精读报告，并自动回写到用户的 Zotero 里。 |

**积木层 `modules/`（17 块）**：`chart_digitize`、`cli`、`config`、`embed`、`evalset`、`figure_crop`、`lib_match`、`llm_client`、`paper_discovery`、`pdf_parse`、`proc_lock`、`query_expand`、`sciverse`、`si_filter`、`snowball`、`subproc`、`zotero_client`

## 待办（可能已过时，动手前先核实）

- 工单列表
- watcher 重复实例（面板发现，2026-08-06）

## 最近踩的坑（全文见 `docs/踩坑记录.md`）

- 踩坑 #38：只看「跟我的库像不像」不够，雪球一开就被高被引通用文献带偏
- 踩坑 #39：用户搜「PBS」，一次暴露三个 bug（缩写歧义 / 漏导入 / 阈值杀光结果）
- 踩坑 #40：通配符 `_*.py` 匹配到 `__init__.py`，一次删光全部 16 块积木
- 踩坑 #41：qwen3.5 本地聊天「卡死」——中文 system 消息极慢 + 思考模式 + 模型名没对齐
- 踩坑 #42：面板 pythonw 打不开 vs 控制台 python 能开——别假设进程是什么就杀

## 想深入时读哪份（**这两份是时间正序的长文件，用 tail 读末尾，别从头读**）

- `docs/踩坑记录.md`（52 KB） — 所有踩过的坑，含根因与解法
- `docs/变更记录.md`（89 KB） — 每次改动的来龙去脉
- `docs/架构宪法_第一性原理.md`（17 KB） — 最高纲领：三条铁律 + 零号/首要判据
- `<某文件夹>/CLAUDE.md` — 那一块的完整说明书，改哪块就读哪份

## 铁律提醒

- **【零号判据】先看真实世界，别用记忆代替调研。**涉及外部现状/具体数字/API 行为，必须查、必须测。
- 改完**先跑体检再重启服务**：`python 平台管理/health_check.py`
- 花钱、不可逆、影响 Zotero 库的操作，**先问用户**。
- 每个改动记 `docs/变更记录.md`，踩坑记 `docs/踩坑记录.md`，并 git commit。
