# 交接文件 · 我们做到哪了

> **本文件由 `平台管理/交接.py` 自动生成，不要手改** —— 手写的文档一定会过时。
> 生成时间：2026-08-26 09:48

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

`结果：8 通过，5 警告，1 失败`

- [WARN] 密钥存放: 凭据库可用（WinVaultKeyring），但一个密钥都没存 —— 5 个待填，请在控制面板里配置
- [FAIL] 配置加载: 缺少: ['DEEPSEEK_KEY', 'ZOTERO_API_KEY', 'MINERU_TOKEN']
- [WARN] Zotero 服务: Zotero 未开（精读/抽取/找文献会失败）
- [WARN] Ollama 服务: Ollama 未跑（问答/向量化会失败）
- [WARN] 公理件自测: 12/16 自测通过（共 17 个公理件）；跳过慢测试 ['chart_digitize']（--full 可跑）；失败: ['embed', 'llm_client', 'query_expand', 'zotero_client']
- [WARN] 后台服务: 缺任务: {'LiteratureAutoSync', 'ZoteroApp', 'OllamaService', 'ZoteroLiteratureWatcher'}

## 👉 下一步该做什么

- **先修体检报的问题**（见上一节），其余都往后放
- **攒精读评测集**：还差「好」3 篇、「差」3 篇。用户在 Zotero 打「读完」标签 → 控制面板「精读评价」里评。评够后即可做「自动质量分」校准，让系统自己发现精读退化。

## 最近做了什么（git 提交，新到旧）

- `08-25` MCP服务/CLAUDE.md 补充 Codex/Claude Code 接入示例（查证官方文档，绝对路径不依赖工作目录）
- `08-25` MCP 服务接入 DSH（HMR 热加载生效）：记录 mcp__zotero__* 工具上线与清理调研克隆
- `08-25` 库房层 MCP 服务落地（MCP服务/）：手写 stdio 协议零依赖 + 10 个只读工具封装 zotero_client；记录调研结论与真实库验证
- `08-25` 控制面板.bat 移除探针；记录计划任务实况更正+ControlPanel任务注册
- `08-25` 面板改控制台python启动+新建精读监听.bat(看门狗)；记录误杀watcher教训(踩坑#42)
- `08-25` 控制面板启动器：捕获pythonw静默报错到panel_launch.log，排查打不开问题
- `08-25` 修 llm_client 本地聊天：模型名走config(.env OLLAMA_MODEL)+关qwen3.5思考，自测3/3过（踩坑#41）
- `08-24` 记录：双机协作搭通（主仓库 chen2994957404-droid + 协作者推送）
- `08-24` README 增加两机协作说明（主仓库 chen2994957404-droid + 协作者工作流）
- `08-24` 记录：本机 Zotero 验证通过（zotero_client 3/3、体检 Zotero OK）

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

- 踩坑 #43：MCP 服务只把 stdout 设成 UTF-8，忘了 stdin —— 中文搜库全变乱码
- 踩坑 #44：默认值选错，让单实例锁在最需要它的时候失效
- 踩坑 #45：体检报「密钥已安全存放」，其实一个密钥都没存
- 踩坑 #46：面板存 `ZOTERO_API_HOST`，积木读 `ZOTERO_LOCAL_API` —— 键名对不上，改了不生效
- 踩坑 #47：「只绑 127.0.0.1」挡得住别的机器，挡不住你自己浏览器里的网页

## 想深入时读哪份（**这两份是时间正序的长文件，用 tail 读末尾，别从头读**）

- `docs/踩坑记录.md`（60 KB） — 所有踩过的坑，含根因与解法
- `docs/变更记录.md`（98 KB） — 每次改动的来龙去脉
- `docs/架构宪法_第一性原理.md`（17 KB） — 最高纲领：三条铁律 + 零号/首要判据
- `<某文件夹>/CLAUDE.md` — 那一块的完整说明书，改哪块就读哪份

## 铁律提醒

- **【零号判据】先看真实世界，别用记忆代替调研。**涉及外部现状/具体数字/API 行为，必须查、必须测。
- 改完**先跑体检再重启服务**：`python 平台管理/health_check.py`
- 花钱、不可逆、影响 Zotero 库的操作，**先问用户**。
- 每个改动记 `docs/变更记录.md`，踩坑记 `docs/踩坑记录.md`，并 git commit。
