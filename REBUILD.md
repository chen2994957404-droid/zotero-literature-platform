# 重构 · 推倒重来的目标结构与分窗施工

> **给 AI 读的。** 用户会说「读 REBUILD.md,做下一窗」。找到台账里第一个没打勾的窗,
> **只做那一窗**,做完更新台账并 commit,然后停下告诉用户可以开新窗。

---

## 〇、这次重构的性质(先读懂,否则你会畏手畏脚)

用户明确授权:**不考虑兼容、不考虑出 bug、项目弄坏都行**。
他之后会**逐个工具单独优化**,所以本次只做一件事:**把每样东西放到它该在的位置**。

- **在分支上做**:第一窗先 `git checkout -b rebuild`。B 机(主力机)继续用 `main`,不受影响。
- **不要为了兼容保留旧路径、旧名字、旧入口。** 中文目录名全部取消。
- **不要问「这样会不会弄坏 X」**,答案是「弄坏也行」。只有一个例外:**不许动 `workflow_data/` 里的数据文件本身**
  (那是不可再生的真实资产),只动目录组织,而且只在 R6 窗做,只在 A 机做。

---

## 一、目标结构(唯一形态)

**组织原则从「按技术分层」改成「按工具切片」**:每个工具是一个自包含的包,
它的代码、MCP 暴露、skill、提示词、评测、测试、文档全在自己的文件夹里。
共用的东西才下沉。这样你以后优化任何一个工具,只需要打开一个文件夹。

```
zotero-platform/
│
├── AGENTS.md                  给所有 agent 的正本(<200 行)
├── CLAUDE.md                  只有一行 @AGENTS.md
├── README.md                  给人的入口
├── pyproject.toml
│
├── tools/                     ★ 工具切片:一个工具 = 一个自包含的包
│   ├── deepread/              精读一篇文献 → 中文图文报告
│   ├── extract/               结构化抽取 → 横向对比表
│   ├── paperdb/               结构化记录 → 可查询的库
│   ├── ask/                   库内问答(含向量化)
│   ├── askworld/              全球文献检索问答
│   ├── discover/              找新文献
│   ├── snowball/              引文雪球扩展
│   ├── digitize/              论文图表 → 数据点
│   ├── direction/             方向地图 / 选题
│   └── curate/                库房维护(标签/改名/去重/同步)
│
├── shared/                    ★ 共用件:被 ≥2 个工具用到才允许住这里
│   ├── kernel/                基础设施(谁都依赖,它不依赖任何人)
│   ├── domain/                纯逻辑(不联网、不知道文件在哪)
│   └── adapters/              外部世界(唯一允许联网的一层)
│
├── host/                      ★ 平台自身(不是能力,是让平台活着的东西)
│   ├── panel/                 控制面板
│   ├── doctor/                体检 + 诊断 + 产物缺口
│   ├── deploy/                部署与更新
│   ├── codegen/               所有生成器
│   └── mcp/                   MCP 协议层(聚合各 tool 的 mcp.py)
│
├── data/                      ★ 数据(单向流,只从上一层构建)
│   ├── raw/                   不可再生:PDF、MineRU 原始产物
│   ├── curated/               可重建但贵:full.md / meta.json / summary.html
│   ├── serving/               随时可重建:compare.md / 向量库
│   ├── state/                 索引不是真相:state.db / papers.db
│   └── logs/
│
├── docs/                      ★ 只放跨工具的档案(工具自己的文档在工具里)
│   ├── explain/               为什么(宪法、对标、方向)
│   ├── howto/                 怎么做(规范、机器分工、部署)
│   ├── reference/             事实(数据契约、tool.toml 格式、API 实测)
│   ├── incidents/             坑的总账(由各工具 INCIDENTS.md 汇总生成)
│   ├── 变更记录.md            日志,不是文档,保持原地
│   └── 待办与需求.md          同上
│
├── specs/                     ★ 还没实现的意图
├── launch/                    ★ 给人双击的入口(路径 ASCII,文件名中文=按钮标签)
├── .claude/                   ★ 全部由生成器产出,禁止手写
│   ├── rules/                 路径触发的规矩
│   └── skills/                从各 tools/<t>/SKILL.md 聚合生成
└── tests/                     ★ 只放跨工具的架构守卫(工具自己的测试在工具里)
```

---

## 二、工具包的固定形状(每个 `tools/<name>/` 一模一样)

```
tools/<name>/
├── tool.toml           唯一元数据源(见下)
├── __init__.py         公开函数 = 这个工具的对外契约
├── <impl>.py           实现,想拆几个文件都行
├── cli.py              人的命令行入口
├── mcp.py              agent 的暴露(tool / resource / prompt)
├── SKILL.md            给 agent:什么时候用我、怎么用、什么时候别用
├── README.md           给人:这是什么、怎么用
├── INCIDENTS.md        这个工具特有的坑
├── prompts/            v1.txt, v2.txt …  **只增不改**
├── evals/
│   ├── golden/         金标输入 + 期望
│   ├── scorers/        评分器
│   └── thresholds.toml
└── tests/              test_*.py
```

`tool.toml`:

```toml
name        = "deepread"
one_line    = "一篇文献 → 中文图文精读报告"
expose      = "prompt"        # tool | resource | prompt | internal
costs_money = true
side_effects  = ["写Zotero", "写data/curated"]
requires_role = "prod"        # none | test | prod
prompts     = ["main@v2", "si@v1"]
```

---

## 三、每种文件的固定位置(这张表就是「格式」)

| 文件种类 | 固定位置 |
|---|---|
| 工具实现代码 | `tools/<t>/*.py` |
| 工具清单 | `tools/<t>/tool.toml` |
| 给人的说明 | `tools/<t>/README.md` |
| 给 agent 的手册 | `tools/<t>/SKILL.md` |
| 人的命令行入口 | `tools/<t>/cli.py` |
| agent 的 MCP 暴露 | `tools/<t>/mcp.py` |
| 提示词 | `tools/<t>/prompts/v<N>.txt` |
| 金标集 / 评分器 / 阈值 | `tools/<t>/evals/` |
| 该工具的测试 | `tools/<t>/tests/` |
| 该工具特有的坑 | `tools/<t>/INCIDENTS.md` |
| 基础设施 | `shared/kernel/<b>/` |
| 跨工具纯逻辑 | `shared/domain/<b>/` |
| 跨工具外部接口 | `shared/adapters/<b>/` |
| 平台自身的工具 | `host/<b>/` |
| 跨工具档案 | `docs/{explain,howto,reference}/` |
| 未实现的意图 | `specs/` |
| 双击入口 | `launch/*.bat` |
| agent 运行时配置 | `.claude/`(**全部生成,手写即违规**) |
| 数据 | `data/{raw,curated,serving,state,logs}/` |

### 四条硬规则(守卫强制,R7 窗实现)

1. **下沉规则**:一段代码被 **≥2 个工具**用到才允许进 `shared/`;只有 1 个用,留在工具里。
   (防止 `shared/` 在一年后变成整个仓库最烂的地方。)
2. **工具隔离**:`tools/*` **不许 import 别的 `tools/*`**。要共用就下沉。
3. **联网只在** `shared/adapters/`。`shared/domain/` 不许 import adapters,也不许知道路径。
4. **没人 import `host/`**;`host/` 可以 import 一切。

---

## 四、老文件 → 新位置(穷尽映射)

### shared/kernel/ ← 原 `core/`
`cli/` `config/` `proc_lock/` `subproc/` `errors.py` `heartbeat.py` `jobs.py` `log.py` `paths.py` `role.py`
(整体平移;`paths.py` 在 R6 窗改成指向新的 `data/` 五层)

### shared/domain/ ← 原 `domain/`
`bibliometrics/` `figure_crop/` `schema/` `si_filter/`

### shared/adapters/ ← 原 `adapters/`(去掉两块)
`embed/` `llm_client/` `openalex/` `pdf_parse/` `sciverse/` `vectordb/` `zotero_client/` `wechat_seed/`
- `adapters/evalset/` → **解散**,拆进各工具的 `evals/`(R5 窗)
- `adapters/snowball/` → **按内容判定**:纯 API 包装留 `shared/adapters/snowball/`;
  若含算法与编排,算法进 `shared/domain/`,编排进 `tools/snowball/`

### tools/deepread/
`pipelines/deepread/*` + `文献精读/` 全部 12 个脚本
(`deepread_v4` `si_deepread` `merge_summary` `mineru_parse` `deepread_batch` `si_batch`
`rerun_pro` `refresh_summary_file` `upload_summaries` `zotero_upload_attachment`
`zotero_watcher` `watchdog`)
→ 逻辑并进 `tools/deepread/`,`cli.py` 收掉所有批量入口,
watcher/watchdog 作为该工具的常驻服务放 `tools/deepread/watcher.py`

### tools/extract/
`pipelines/extract/*` + `数据抽取/{extract_batch,extract_library,extract_structured,filter_domain,重抽向导,试一试本地模型}.py`

### tools/paperdb/
`pipelines/paper_db/*` + `数据抽取/查询库.py`

### tools/ask/
`库内问答/{ask,vectorize,vectorize_library}.py` + `pipelines/query_expand/*` + `pipelines/lib_match/*`
(向量化是问答的前置,属于同一个工具)

### tools/askworld/
`库内问答/ask_world.py` + `找新文献/search_global.py`

### tools/discover/
`pipelines/paper_discovery/*` + `找新文献/{discover,find_papers,collect,import_by_doi,zotero_add_thesis}.py`

### tools/snowball/
雪球的编排逻辑(见上 `adapters/snowball` 的判定)

### tools/digitize/
`pipelines/chart_digitize/*`

### tools/direction/
`pipelines/direction_map/*` + `找新文献/{brainstorm,方向地图}.py`

### tools/curate/
`库房维护/` 全部 7 个脚本(`auto_sync` `autotag` `backfill_meta` `delete_junk` `list_junk` `tag_to_nested` `zotero_rename`)

### host/
- `host/panel/` ← `平台管理/{panel,panel_launch,打开面板}.py`
- `host/doctor/` ← `平台管理/{health_check,诊断报告,查产物缺口}.py`
- `host/deploy/` ← `平台管理/更新平台.py`
- `host/codegen/` ← `平台管理/交接.py`(+ 后续所有生成器)
- `host/mcp/` ← `MCP服务/{mcp_stdio,selftest}.py`;`zotero_server.py` **解散**,
  它的 10 个工具按归属拆进 `tools/*/mcp.py`(查询类多半属于新建的 `tools/library/` 或并入 `ask`)

### launch/ ← 根目录 6 个 .bat
`控制面板.bat` `更新平台.bat` `诊断报告.bat` `精读监听.bat` `比一比两个模型.bat` `重抽缺SI的文献.bat`
→ 移进 `launch/`,**文件名保持中文**(那是给人看的按钮标签,不是代码路径),内部路径全改新结构

### tests/ ← 原 `tests/`
- 架构守卫类留 `tests/`:`test_architecture.py` `test_no_undefined_names.py`
- 其余按归属拆进各工具:`test_core_*` → `shared/kernel/*/tests/`;
  `test_pipelines_deepread` `test_watcher_decision` `test_watchdog_decision` → `tools/deepread/tests/`;
  `test_adapters_vectordb` → `shared/adapters/vectordb/tests/`;
  `test_panel_config` → `host/panel/tests/`;`test_artifact_gaps` → `host/doctor/tests/`

### docs/
- `explain/` ← 架构宪法_第一性原理 · 对标报告 · 正文数据关联_方向说明 · 架构重构_v2总体设计 · 积木采购清单
- `howto/` ← 代码规范_标准脚本模板 · 两台机器的分工 · 测试端与阶段3路线
- `reference/` ← 数据契约 · API_verified · 架构总览 · 演进规划与模块地图 · 视觉模型选择_参考
- `incidents/` ← 踩坑记录(R7 窗按工具切片,总账留这里)
- 原地不动:`变更记录.md` `待办与需求.md`

### data/ ← `workflow_data/`(R6 窗,只在 A 机)
- `raw/` ← MineRU 原始解析产物(现在散在 `library/<KEY>/parsed/` 里,需要甄别)
- `curated/` ← `library/`(full.md / meta.json / summary.html)
- `serving/` ← `structured/` `vector_db/` `direction/`
- `state/` ← `state.db*` `papers.db` `evalset.json` `_last_search.json`
- `logs/` ← `logs/`
- `backup/` 保持

### 直接删除
- `归档_旧版本/`(git 就是归档)
- 所有 `__pycache__/`
- `zotero_literature_platform.egg-info/`
- `平台管理/panel_launch.log`(日志不进版本库)

---

## 五、进度台账

| 窗 | 内容 | 状态 | 实际做了什么 |
|---|---|---|---|
| R1 | 开分支 + 建骨架 + 搬 shared/ 与 host/ | [x] | `rebuild` 分支已开。`core/domain/adapters` → `shared/{kernel,domain,adapters}`；`平台管理`+`MCP服务` → `host/{panel,doctor,deploy,codegen,mcp}`，中文脚本名换成 ASCII；115 个文件批量改 import；`paths.py` 新增 `CODE_ROOTS`、`CODE_RINGS` 改成带斜杠相对路径；pyproject 改成 `tools*/shared*/host*/pipelines*` 并重装；删 `归档_旧版本`/pycache/egg-info；3 个 .bat 内部路径已改。**pytest 195 全过、离线体检 10/0/0、完整体检 16/2/0 与重构前基线一致。**踩坑 #78 #79 #80。 |
| R2 | 切出 deepread / extract / paperdb / digitize | [x] | 四个工具已成包。`pipelines/{deepread,extract,paper_db,chart_digitize}` + `文献精读/`（12 脚本）+ `数据抽取/`（7 脚本）→ `tools/{deepread,extract,paperdb,digitize}`，两个中文文件夹**已删**。六个精读脚本并成 `deepread/batch.py`、三个抽取脚本并成 `extract/batch.py`；新增 `deepread/tags.py`（标签状态机从 watcher 独立）；`zotero_watcher.py`→`watcher.py`。**删了 5 个纯薄壳**（deepread_v4/si_deepread/merge_summary/zotero_upload_attachment/mineru_parse —— 最后一个是 `adapters/pdf_parse` 的第二份实现，违反「联网只在 adapters」）。`extract_library` 的裸 urllib 改走适配层。测试进 `tools/deepread/tests/`，`testpaths` 加 `tools`；`CODE_RINGS` 加 `'tools'`（否则体检不再跑这四个工具的自测）。改了 health_check（关键入口改成按**模块名**查）/ panel / update / auto_sync / 架构守卫 / 4 个 .bat。**pytest 195 全过、tools/ 37 全过、离线体检 10/0/0、完整体检 16/2/0 与 R1 基线一致。**踩坑 #81。留了两处 `tools` 调 `tools`（watcher→extract、extract→paperdb），已记进待办等 R7 定夺。 |
| R3 | 切出 ask / askworld / discover / snowball / direction / curate | [ ] | |
| R4 | 每工具补齐五件套(tool.toml / README / SKILL / cli / mcp) | [ ] | |
| R5 | prompts 与 evals 归位到各工具 | [ ] | |
| R6 | data/ 五层重排 + launch/ + 清死文件 | [ ] | |
| R7 | 守卫重写 + .claude 全生成 + docs 归类 + 终验 | [ ] | |

---

# R1 · 开分支 + 建骨架 + 搬 shared/ 与 host/

**第一件事**:`git checkout -b rebuild`。之后所有窗都在这个分支上。

1. 按第一节建空目录骨架(`tools/ shared/ host/ docs/{explain,howto,reference,incidents} specs/ launch/`)。
2. `core/` → `shared/kernel/`;`domain/` → `shared/domain/`;`adapters/` → `shared/adapters/`
   (`evalset` 先原样搬,R5 再解散)。
3. `平台管理/` 与 `MCP服务/` 按第四节拆进 `host/`。
4. 全项目改 import:`from core import` → `from shared.kernel import`,以此类推。
   **用脚本批量改,不要手改**,改完 `grep -rn "^from core\|^import core\|from adapters\|from domain\|from pipelines"` 确认为空。
5. `pyproject.toml` 的 `packages.find` 改成 `["tools*", "shared*", "host*"]`,重跑 `pip install -e . --no-deps`。
   ⚠ 踩坑 #55:装完**当前进程仍 import 不到**,要重开进程验证。
6. 删 `归档_旧版本/`、所有 `__pycache__/`、`egg-info/`、`panel_launch.log`;`.gitignore` 补上。

**验收**:`python -c "from shared.kernel import paths, jobs"` 成功;
`python -m pytest -q` 能收集到用例(**允许有失败**,那是后面窗的活);`git status` 干净。

---

# R2 · 切出 deepread / extract / paperdb / digitize

按第四节映射,把这四个工具的代码从 `pipelines/` 与中文文件夹里合并进 `tools/<name>/`。

- 每个工具建 `__init__.py`,把**对外契约**(公开函数)写进 docstring
- 批量脚本的逻辑并进工具,不要保留一个脚本一个文件的旧形态
- 暂时不写 `tool.toml` / `SKILL.md` / `mcp.py`(R4 统一做)
- 该工具的测试从 `tests/` 搬进 `tools/<t>/tests/`

**验收**:四个工具都能 `import`;`pytest tools/` 能跑;`git status` 干净。

---

# R3 · 切出其余六个工具

同 R2,处理 `ask` `askworld` `discover` `snowball` `direction` `curate`。

⚠ `snowball` 要先判定:读 `shared/adapters/snowball/` 的代码,
纯 API 包装就留在 adapters,含算法与编排就拆。**在提交信息里写清判定理由。**

做完之后 `pipelines/` 与全部中文文件夹应该是空的 → **删掉**。

**验收**:`ls` 根目录不再有中文文件夹和 `pipelines/`;十个工具全部可 import。
⚠ 删掉 `pipelines/` 之后，记得把 `pyproject.toml` 的 `packages.find` 里的 `"pipelines*"` 一并删掉，再重装一次包。

---

# R4 · 每工具补齐五件套

给 `tools/*` 每个补上 `tool.toml` / `README.md` / `SKILL.md` / `cli.py` / `mcp.py`。

- `tool.toml` 格式见第二节。`expose` 的判据:
  **只读且便宜 → `tool`;只读数据 → `resource`;花钱或有副作用 → `prompt`。**
  `costs_money = true` 或 `side_effects` 非空的**一律不能是 `tool`**。
- `SKILL.md` 必须写「**什么时候别用我**」——模型选错工具的主因是不知道边界。
- `mcp.py` 只做参数转换,**不许有逻辑**。
- `host/mcp/` 改成聚合各 `tools/*/mcp.py`,不再手写工具清单。

**验收**:`python host/mcp/server.py --list` 列出三类且与各 `tool.toml` 一致;`pytest` 能跑。

---

# R5 · prompts 与 evals 归位

1. 每个用到 LLM 的工具建 `prompts/v<N>.txt`,**版本只增不改**。
   迁 `pipelines/deepread/_sys_prompt_v2.txt`;`grep -rn` 找出其余硬编码的长提示词字符串一并迁出。
   写一个薄读取器放 `shared/kernel/`(不联网,所以不是 adapter)。
2. 解散 `shared/adapters/evalset/`,拆进各工具的 `evals/`。
   `evalset.json` 里的现有评价数据按工具分。
3. 每个工具建 `evals/{golden,scorers}/` 与 `thresholds.toml`,没有数据也要有空骨架和 README。

**验收**:`grep -rn "_sys_prompt" --include="*.py" .` 无结果;`adapters/evalset` 不存在;
每个 LLM 工具都有 `prompts/` 与 `evals/`。

---

# R6 · data/ 五层重排 + launch/ + 清死文件

⚠ **只在 A 机做,只动目录组织,不动文件内容。先 `git status` 确认 data 目录已在 `.gitignore` 里。**

1. `workflow_data/` → `data/`,按第四节分五层。**先复制再删原目录**,确认无误再删。
2. 改 `shared/kernel/paths.py` 指向新五层——**全系统只有这一个文件知道目录长什么样**,
   所以这一步只改一个文件。改完 `grep -rn "workflow_data"` 应只剩文档里的历史记述。
3. 根目录 6 个 `.bat` 移进 `launch/`,内部路径改新结构,**文件名保持中文**。

**验收**:`python -c "from shared.kernel import paths; print(paths.LIBRARY)"` 指向 `data/curated`;
`grep -rn "workflow_data" --include="*.py" .` 无结果;双击 `launch/控制面板.bat` 能起面板。

---

# R7 · 守卫重写 + .claude 全生成 + docs 归类 + 终验

1. **重写 `tests/test_architecture.py`**,守第三节的四条硬规则:
   - `tools/*` 不许互相 import
   - 联网只在 `shared/adapters/`
   - `shared/domain/` 不许 import adapters、不许出现路径字面量
   - 没人 import `host/`
   - 每个 `tools/<t>/` 必须有全套七件(`tool.toml` `__init__` `cli` `mcp` `SKILL.md` `README.md` `tests/`)
   - `costs_money`/`side_effects` 与 `expose` 的一致性
   - **下沉规则**:`shared/` 里只被 1 个工具引用的块 → 报警
   每加一条守卫,**故意违反一次确认它真的会红**。
2. **`.claude/` 全部改成生成**:`host/codegen/` 从各 `tools/*/SKILL.md` 聚合出 `.claude/skills/`,
   从 `docs/howto/代码规范` 生成带 `paths:` 的 `.claude/rules/`,
   从各 `INCIDENTS.md` 汇总 `docs/incidents/`。手写的一律删掉。
3. **`docs/` 按第四节归类**,改完 `grep -rn "docs/"` 修所有引用。
4. **重写 `AGENTS.md`**(<200 行)与 `README.md`,`CLAUDE.md` 只留 `@AGENTS.md`。
   目录树由 `host/codegen/` 生成。
5. **终验**:`pytest -q` 全过 · `python host/doctor/health_check.py --offline` 0 失败 ·
   面板能开 · MCP `--list` 正确 · `grep -rn` 无失效引用。

**做完告诉用户**:重构在 `rebuild` 分支上完成,`main` 未动,B 机不受影响。
合并前需要他决定:B 机怎么切过去(自启任务路径全变了,要重新注册)。

---

## 六、明确不做

1. **不为兼容保留任何旧路径、旧名字、旧入口。**
2. **不引编排框架**(LangGraph / Temporal):`shared/kernel/jobs` 已覆盖断点续跑。
3. **不做 `plugin.json` 打包**:该标准 2026-08-06 才发布,Claude Code 不在启动客户端名单里。
4. **不动 `data/` 里的文件内容**,只动目录组织。
5. **不在重构窗里优化任何工具的逻辑** —— 用户说了他之后逐个优化。
   本次只搬家、只补形状。看到 bug 记进 `docs/待办与需求.md`。
