# 框架重构 · 分窗施工手册

> **这份文件是给 AI 读的,不是给人读的。** 用户会在每个新对话窗口里说
> 「读 REBUILD.md,做下一窗」。你要做的就是:找到第一个没打勾的窗,**只做那一窗**,
> 做完更新台账并 commit,然后停下来告诉用户「本窗完成,可以开新窗了」。

---

## 〇、开场:你必须先做的三件事

1. **读本文件的「进度台账」**,找到第一个 `[ ]` 的窗口。
2. **只读那一窗的小节**(每一窗都写成自给自足的,不必读别的窗,也不必读原始对话)。
   如果那一窗让你读某份文档,再去读。
3. **动手前先跑一次基线**,确认起点是干净的:

```bash
python -m pytest -q
```

```bash
python 平台管理/health_check.py --offline
```

三条(含 `git status`)都干净才开工。有红先修红,或者告诉用户。

**不要一次做两窗。** 每一窗都被设计成「结束时仓库处于绿色、可用、已提交」的状态。
跨窗做等于把仓库留在半迁移状态过夜,那是这次重构唯一可能出真事故的方式。

---

## 一、铁律(每一窗都适用,违反就停下来问用户)

1. **绝不物理搬迁中文文件夹**(`文献精读/` `数据抽取/` `库内问答/` `找新文献/` `库房维护/` `平台管理/`)。
   根目录 6 个 `.bat` 和 **B 机的 4 个自启任务**都硬编码了这些路径。
   本次重构的「暴露面 / 运维」是**逻辑分层**——靠 manifest 声明 + 守卫强制,
   **不靠目录位置**。想让目录名整齐是审美,代价是弄坏用户主力机,不划算。
2. **绝不重命名 `core/` `domain/` `adapters/` `pipelines/`**。它们已经稳定,改名有成本无收益。
3. **每一窗结束必须三绿**:`pytest -q` 全过 · `health_check.py --offline` 0 失败 · `git status` 干净(已提交)。
4. **每一窗结束必须更新本文件的台账**(打勾 + 一行实际做了什么),并写进 `docs/变更记录.md`。
5. **踩到新坑当场记** `docs/踩坑记录.md`(编号 + 现象 + 根因 + 解法),用 Python `io.open(...encoding='utf-8')` 追加,
   避开 PowerShell 的 GBK 乱码。
6. **不许顺手优化**。看到别的问题,记进 `docs/待办与需求.md`,不要在本窗里动。
   本次重构的最大风险不是做错,是**范围失控**。
7. **A 机不许写真实 Zotero、不许跑花钱的批量作业。** 需要验证写回时用 `ROLE=test`。
8. **能生成的绝不手写,能被守卫强制的绝不写成文档。** 这是整套设计的唯一质量保证。
   任何时候你打算「手写一份说明」,先问:这能不能从代码或已有文档生成?

---

## 二、进度台账(做完一窗回来打勾)

| 窗 | 内容 | 状态 | 实际做了什么 |
|---|---|---|---|
| W0 | 止血:生成器不再骗人 + 清死代码 | [ ] | |
| W1 | 知识层四级归位(AGENTS.md / rules / skills) | [ ] | |
| W2 | manifest 规范 + 校验守卫 | [ ] | |
| W3 | 从 manifest 生成(树 / README / 面板清单) | [ ] | |
| W4 | 暴露面:MCP 三类由 manifest 生成 | [ ] | |
| W5 | prompts/ 独立并带版本 | [ ] | |
| W6 | evals/ 升为一等公民 + 回归守卫 | [ ] | |
| W7 | specs/ + docs 按 Diátaxis 归类 + 收尾 | [ ] | |

---

## 三、设计总纲(压缩版,任何一窗都可以只看这一节)

### 唯一的第一性原理

> **按「什么会让它改变」分家。同一个抽屉里的东西总是一起变;不同抽屉的能独立变。**

这是项目宪法「按稳定性决定自己做还是用现成」的推广:从代码推广到全部资产。

三条推论:

- 变化速率不同 → 必须分家(提示词一周改三次,`core/paths` 一年不动)
- 消费者不同 → 必须分家(人要「双击能跑」,agent 要「判据 + schema」)
- 能生成的绝不手写(手写副本一定分叉,**过时文档比没文档更坏**)

### 这次重构在解决什么

四环(`core`/`domain`/`adapters`/`pipelines`)只解决了「代码住哪」。
另外两条轴一直无家可归,于是全挤进了 `CLAUDE.md` 和 `平台管理/`:

| 轴 | 状态 |
|---|---|
| 代码轴:这段逻辑住哪 | 已解决(四环) |
| **消费者轴**:给人 / 给建造 agent / 给使用 agent | 本次解决 |
| **资产轴**:提示词 / 评测 / 意图 / 运维 / 知识 | 本次解决 |

### 十个抽屉与收纳判据

| 抽屉 | 只收 | 明确不收 | 本次 |
|---|---|---|---|
| `core/` | 谁都依赖、不依赖任何人 | 任何知道业务的东西 | 不动 |
| `domain/` | 纯逻辑、可离线测 | 路径、网络 | 不动 |
| `adapters/` | 与外部世界的接触点 | 业务顺序 | 不动 |
| `pipelines/` | 「先 A 再 B」的顺序知识 | 原子能力、网络 | 不动 |
| **暴露面**(逻辑层) | 只做参数转换与展示的壳 | 任何逻辑 | W4 声明 |
| `prompts/` | 喂给模型的文本 + 版本 | 拼装逻辑 | W5 新建 |
| `evals/` | 金标输入、期望、评分器、阈值 | 生产代码 | W6 新建 |
| `specs/` | 还没实现的意图 | 已实现的东西 | W7 新建 |
| **运维**(逻辑层) | 让平台活着的工具 | 平台的能力本身 | W2 声明 |
| `docs/` | 单一事实源的档案 | 任何副本 | W7 归类 |
| `.claude/` | **全部由生成器产出**的工作副本 | 手写长文 | W1 |

### 知识分级(官方四级,判据)

| 这条知识…… | 放哪 | 何时进上下文 |
|---|---|---|
| 每次会话都要知道 | `CLAUDE.md` / `AGENTS.md` | 永远(目标 <200 行) |
| 只在碰某类文件时要 | `.claude/rules/` 带 `paths:` | 读到匹配文件时 |
| 只在做某类任务时要 | `.claude/skills/` | 任务相关时 |
| 我总忘且忘了代价大 | **hook** | 不进上下文,强制执行 |
| 完整档案 | `docs/` | 被指名才读 |

### manifest:一处声明,多处生成(本次重构的核心产物)

每块一份声明,从它生成:MCP 工具清单、面板按钮、README 能力表、
守卫检查表、提示词→评测追踪、目录树。**新增任何东西只需填这张表。**

---

# W0 · 止血:让生成器不再骗人

### 前置

基线三绿。

### 目标

CLAUDE.md 里那棵自动生成的目录树,现在写的数字是错的,而它是新会话读到的第一份东西。
让它永远正确,并清掉两处死代码。

### 为什么(必读,否则你会觉得这一窗不重要)

实测:自动区块里写 `domain` 3 块(实际 4)、`adapters` 9 块(实际 11)、
`pipelines` 7 块(实际 8),而且还在说「积木层 `modules/`」——`modules/` 早就不存在了。
根因是 `平台管理/交接.py` 只在有人手动跑时才更新。
**一个会骗人的地图比没有地图更危险**:新会话会自信地答错。

### 步骤

1. 跑一次 `python 平台管理/交接.py`,确认树被刷新、数字对上。
2. 读 `平台管理/交接.py` 的 `blocks()` / `tree()`,**找出为什么它还在说「积木层 modules/」**
   ——那是硬编码的旧措辞,改成从实际环名生成。
3. 加一个 hook,让结构变化后自动重跑生成器。写进 `.claude/settings.json`
   (**不是** `settings.local.json`,这条要进版本库):
   `PostToolUse` 匹配 `Write|Edit`,当路径命中 `(core|domain|adapters|pipelines)/**/__init__.py`
   时跑 `python 平台管理/交接.py`。
   ⚠ 先读 `docs/踩坑记录.md` 里关于**子进程弹窗**和**编码**的条目,别让 hook 弹黑窗口或吐乱码。
4. 清死代码:
   - `pyproject.toml` 的 `include = ["modules*", ...]` 去掉 `modules*`(该包已不存在)
   - 删掉 `归档_旧版本/`(git 就是归档,仓库里不该有归档目录)。**删之前先确认没人引用它**:
     `grep -rn "归档_旧版本" --include="*.py" .`

### 验收

- `python 平台管理/交接.py` 后,CLAUDE.md 的树里各环块数与 `ls` 结果一致
- 树里不再出现 `modules/`
- `python -m pytest -q` 全过
- `python 平台管理/health_check.py --offline` 0 失败

### 收尾

更新台账 → 记 `docs/变更记录.md` → `git commit`。

### 不要做

不要顺手改 CLAUDE.md 的手写部分(那是 W1 的活)。

---

# W1 · 知识层四级归位

### 前置

W0 完成。基线三绿。

### 目标

把「每次会话都加载」的东西压到官方建议的预算内,把其余的下沉到**按需加载**的三级。

### 为什么

- 官方文档:`CLAUDE.md` **目标低于 200 行**,越长遵守率越低。当前 230 行。
- 官方文档明确:**Claude Code 读 `CLAUDE.md`,不读 `AGENTS.md`**。
  但 Cursor / Codex / Copilot / Windsurf 读 `AGENTS.md`。
  正确做法是 `AGENTS.md` 作正本,`CLAUDE.md` 第一行 `@AGENTS.md` 导入。
  ⚠ **本项目在 Windows,必须用 `@import`,不能用 symlink**(symlink 要管理员权限,官方也推荐 import)。
- `.claude/rules/` 支持 `paths:` frontmatter,**只在读到匹配文件时才加载**。
  项目的七条代码红线属于这一类:不该常驻,该在碰 `.py` 时才出现。**当前完全没用这个机制。**
- Skill 的预算:发现层(name+description)30–50 token,激活层正文 ≤8000 token。

### 步骤

1. **建 `AGENTS.md` 作正本**,内容 = 当前 `CLAUDE.md` 里「每次会话都要知道」的那部分:
   项目是什么 / 用户是谁(不懂编程) / 自动生成的目录树 / 两台机器警告 /
   读 HANDOVER / 能力速查表 / 数据资产 / 四环表 / 语言约定 / 模型分工 / 零号判据一句话 /
   验证自主性 / 日志纪律 / rules 与 skill 索引。**目标 <200 行。**
2. **`CLAUDE.md` 改成**:第一行 `@AGENTS.md`,下面只留 Claude Code 专属补充。
   ⚠ 决定 `AUTO:结构` 自动区块放哪个文件(建议 `AGENTS.md`),
   并**同步改 `平台管理/交接.py` 里的 `CLAUDE_MD` 常量**,否则生成器会写错文件。
3. **建 `.claude/rules/`**,把「碰到某类文件才需要的规矩」从常驻区搬进来,每条带 `paths:`:
   - `code-style.md` → `paths: ["**/*.py"]`:标准开头 4 行、`core/cli` 取参、`core/config` 取配置、
     `core.paths` 取路径、`core.log` 打日志、命名约定
   - `ring-boundaries.md` → `paths: ["core/**", "domain/**", "adapters/**", "pipelines/**"]`:
     依赖方向、联网只在 adapters、domain 不许知道路径、新增积木三件套
   - `side-effects.md` → `paths: ["adapters/zotero_client/**", "pipelines/**", "文献精读/**", "库房维护/**"]`:
     `role.require_prod` 守卫怎么写(必须在函数体里,不能在模块顶层)
4. **调整现有 4 个 skill 的边界**,消除与 rules 的重复:
   `.claude/skills/code-redlines` 的内容大部分应下沉进 rules(路径触发更准),
   skill 只留「改完的验证顺序」「新增积木三件套」这类**任务级**的东西。
   `troubleshoot` / `research-first` / `two-machines` 保持不动。
5. 在 `AGENTS.md` 里放一张**索引表**:哪个 rule 管什么、哪个 skill 什么时候读。

### 验收

- `AGENTS.md` 手写部分 <200 行(`wc -l`)
- `CLAUDE.md` 第一行是 `@AGENTS.md`
- `python 平台管理/交接.py` 仍能正确写入自动区块(**跑一次确认写对了文件**)
- `pytest -q` 全过;`health_check.py --offline` 0 失败

### 收尾

更新台账 → `docs/变更记录.md` → commit。
提醒用户:**下个窗口开头可以用 `/context` 确认 memory files 里出现了 CLAUDE.md**。

### 不要做

不要把 `docs/` 里的长文复制进 rules 或 skill。**引用,不复制。**

---

# W2 · manifest 规范 + 校验守卫

### 前置

W1 完成。基线三绿。

### 目标

给每一块能力一份**机器可读的自我声明**。这是整套框架的地基——后面三窗都靠它。

### 为什么

现在「这块是什么、暴露给谁、花不花钱、有没有副作用、该住哪一环」这些事实
散落在各块 `CLAUDE.md` 的正文里,只有人能读。
变成结构化声明后可以**一处声明、多处生成**,并且
**架构违规从「靠人 review」变成「填错一个字段就 pytest 红」**。

### 步骤

1. **定格式**。每块目录下放 `block.toml`(标准库 `tomllib` 可读,不加依赖):

```toml
name        = "deepread"
layer       = "pipeline"     # core|domain|adapter|pipeline|surface|ops
one_line    = "一篇文献 → 中文图文精读报告"
expose      = "prompt"       # tool|resource|prompt|internal  (W4 才用,先填)
volatility  = "需求驱动"      # 稳定|我们的想法|外部世界|需求驱动
costs_money = true
side_effects  = ["写Zotero", "写workflow_data"]
requires_role = "prod"       # none|test|prod
prompts     = []             # W5 才填
```

   **把这份格式写进 `docs/`(W7 会移进 `docs/reference/`)。**

2. **给现有全部块补上**:`core`(10)、`domain`(4)、`adapters`(11)、`pipelines`(8),
   以及中文文件夹的入口(按文件夹给一份即可,`layer = "surface"` 或 `"ops"`)。
   `one_line` **从各块 `CLAUDE.md` 首段抽**,不要重写
   (`平台管理/panel.py` 已有 `first_line()` 可复用)。
3. **加守卫**(`tests/test_manifest.py`):
   - 每块必须有 `block.toml`,必填字段齐全
   - `layer` 与实际所在目录一致
   - `volatility = "外部世界"` 的块必须在 `adapters/`
   - `side_effects` 含「写Zotero」的块,`requires_role` 不能是 `none`
   - `expose` 取值合法

### 验收

- 每块都有 `block.toml`,`pytest -q` 全过
- 故意把某块 `layer` 填错 → pytest 变红(**必须实测一次,确认守卫真在守**)
- `health_check.py --offline` 0 失败

### 收尾

更新台账 → `docs/变更记录.md` → commit。

### 不要做

不要在本窗写生成器(那是 W3)。本窗只做「声明 + 校验」。

---

# W3 · 从 manifest 生成

### 前置

W2 完成。基线三绿。

### 目标

把现在手工维护、且已被证明会过时的三处清单,改成从 manifest 生成。

### 为什么

W0 修的是「生成器没自动跑」,本窗修的是「还有几处根本没有生成器」:
`README.md` 的能力表、面板的积木一览、各文档里的块清单——全是手写的,全会过时。

### 步骤

1. 写生成器 `平台管理/生成清单.py`(或并入 `交接.py`),从全部 `block.toml` 产出:
   - **目录树**:替掉 `交接.py` 里 `tree()` 的手工措辞,块数与 `one_line` 全来自 manifest
   - **README 能力表**:给用户看的中文表,列 `one_line` + 是否花钱
   - **面板的积木一览**:`平台管理/panel.py` 现在从各文件夹 `CLAUDE.md` 首段抓,改成读 manifest
2. 三处都用 `<!-- AUTO:xxx 开始/结束 -->` 包起来,与现有 `AUTO:结构` 同一套机制。
3. 把 W0 的 hook 扩展到「`block.toml` 变化也重跑生成器」。

### 验收

- 改一块的 `one_line` → 跑生成器 → README / 目录树 / 面板三处同时变
- `pytest -q` 全过;`health_check.py --offline` 0 失败
- 面板起得来(`python 平台管理/panel.py` 能启动即可,不必真开浏览器)

### 收尾

更新台账 → `docs/变更记录.md` → commit。

---

# W4 · 暴露面:MCP 三类由 manifest 生成

### 前置

W3 完成。基线三绿。

### 目标

把 `MCP服务/` 从「手写的 10 个只读 Zotero 工具」升级成「从 manifest 生成的三类暴露面」。

### 为什么(这一窗的判据最重要,务必读懂)

MCP 规范有**三个原语**,分类轴是「**谁决定什么时候用它**」:

| 原语 | 谁决定 | 收什么 | 本项目的例子 |
|---|---|---|---|
| **tool** | 模型 | 只读、便宜、可重试的原子 | 搜库、取全文、向量检索、OpenAlex 查询 |
| **resource** | 应用 | 只读**数据** | `compare.md`、`structured/*.json`、`jobs` 进度 |
| **prompt** | 人 | 花钱/有副作用/有状态机的**组合** | 精读一篇、全库重抽、雪球、图表数字化 |

**判据:一个能力允许模型自由编排,当且仅当它错了没有代价。**
精读一篇要烧 MineRU + DeepSeek 的钱,背后还有 `core/jobs` 状态库和 Zotero 标签状态机——
**那个顺序本身就是知识,不能让模型每次重新发明**,所以它必须是 prompt,不是几个 tool。

对应到四环有一个不是巧合的映射:**`pipelines`(定理)→ prompt,`adapters`/`domain`(公理)→ tool。**

### 步骤

1. 复核每块 manifest 的 `expose` 填得对不对(按上表判据)。
   `costs_money = true` 或 `side_effects` 非空的,**一律不能是 `tool`**——加一条守卫。
2. 改 `MCP服务/zotero_server.py`:工具清单从 manifest 生成,不再手写。
3. **新增 resource 类**:`compare.md`、`compare_PBS.md`、`structured/<KEY>.json`、
   `library/<KEY>/summary.html`、`jobs.summary()`。
4. **新增 prompt 类**:精读一篇 / 重抽一篇 / 图表数字化。
   ⚠ 保持 v1 的「只读」边界不被破坏:prompt 里凡是会写 Zotero 的,
   必须经过 `role.require_prod`,A 机默认拒绝。
5. **加守卫**:暴露面的实现文件不得包含业务逻辑。选一个能自动判的规则
   (单文件行数上限,或禁止 import 除 `pipelines`/`adapters` 之外的东西),**写清楚理由**。

### 验收

- `python MCP服务/selftest.py` 全过
- `python MCP服务/zotero_server.py --list` 能列出三类,且与 manifest 一致
- 故意把一个 `costs_money = true` 的块标成 `expose = "tool"` → pytest 红(**实测一次**)
- `pytest -q` 全过;`health_check.py --offline` 0 失败

### 收尾

更新台账 → `docs/变更记录.md` → commit。
告诉用户:DSH 那边的 MCP 配置不用改(serverName 与启动方式未变)。

---

# W5 · prompts/ 独立并带版本

### 前置

W4 完成。基线三绿。

### 目标

把提示词从代码里抽出来,变成带版本的独立资产。

### 为什么

- 提示词的变化速率比代码高一个数量级,按第一性原理必须分家。
- 业界共识:提示词应与应用代码解耦、独立版本化,以支持安全回滚与对照实验。
- **`core/jobs` 已经在记 `prompt_ver` 了**——状态库比目录结构更先进,本窗补齐另一半。
  补齐后,「提示词升到 v3,谁该重跑」才真能查(`jobs.stale()` 已有此接口)。
- 现状:`pipelines/deepread/_sys_prompt_v2.txt` 埋在代码目录,其余提示词散在字符串里。

### 步骤

1. 建 `prompts/<能力>/<用途>/v<N>.txt`,例如 `prompts/deepread/main/v2.txt`。
   **版本只增不改**:改提示词 = 加新版本文件,旧的原样留着(否则无法回滚、无法对照)。
2. 写一个极薄的读取器:`get_prompt('deepread/main', ver=2)`。
   放 `core/` 或 `domain/`——**它不联网,所以不属于 adapters**。
   在 manifest 的 `prompts` 字段登记引用。
3. 迁 `pipelines/deepread/_sys_prompt_v2.txt`,代码改为按版本引用。
   `grep -rn` 找出其余硬编码的长提示词字符串,一并迁出。
4. **加守卫**:代码里禁止裸提示词引用(必须带版本号);`prompts/` 下已有版本文件不许被修改
   (比对哈希清单,或至少强制文件名带版本)。

### 验收

- `grep -rn "_sys_prompt" --include="*.py" .` 无结果
- 单篇精读能跑通(A 机 `ROLE=test`,**不回写真实库**)。
  若 A 机跑不了,写清验证方式交给用户在 B 机双击验证,**不要假装验证过了**。
- `pytest -q` 全过;`health_check.py --offline` 0 失败

### 收尾

更新台账 → `docs/变更记录.md` → commit。

### 不要做

不要顺手改提示词内容。本窗只搬家、只加版本机制。**改内容会让 W6 的基线失效。**

---

# W6 · evals/ 升为一等公民

### 前置

W5 完成。基线三绿。

### 目标

把评测从「待办事项」变成「目录 + 守卫」。

### 为什么

业界共识里最一致的一条:**金标数据集是 LLM 生产栈里最重要的可靠性资产,
比框架选型和指标选择都重要**。规范做法是:任何改动提示词、模型版本或检索配置的提交,
都要对金标集跑一遍,回归超阈值就不许合入。

本项目现状:`adapters/evalset` 存在,但只评了 1 篇(需好/差各 ≥3 篇才能校准),
而且它住在 `adapters/`——**评测不是「与外部世界的接触点」,归错环了**。

### 步骤

1. 建 `evals/`:
   - `evals/golden/` 金标集(输入 + 期望/评分标准),**版本化**
   - `evals/scorers/` 评分器
   - `evals/thresholds.toml` 阈值
   - `evals/README.md` 怎么加一条金标、怎么跑
2. 把 `adapters/evalset` 的逻辑归位到 `evals/`(若为纯逻辑也可入 `domain/`)。
   ⚠ 先 `grep -rn "evalset"` 找出谁在用,**面板的「精读评价」功能不能坏**。
3. **加守卫(本次重构最有价值的一条)**:
   提交里改动了 `prompts/**` 或模型配置,却没有对应的 eval 运行记录 → pytest 红。
   实现可以很简单:比对 `prompts/` 的版本清单与 `evals/` 里记录的已评版本。
4. 在 `AGENTS.md` 的日志纪律里加一句:改提示词必须跑 eval。

### 验收

- `pytest -q` 全过;`health_check.py --offline` 0 失败
- 面板的「精读评价」仍能打开
- 故意加一个未评测的提示词版本 → pytest 红(**实测一次**)

### 收尾

更新台账 → `docs/变更记录.md` → commit。
**提醒用户**:金标集还差「好」2 篇、「差」3 篇,需要他在 Zotero 打「读完」标签后到面板里评。
这件事只有他能做,你做不了。

---

# W7 · specs/ + docs 归类 + 收尾

### 前置

W6 完成。基线三绿。

### 目标

给「还没做的意图」一个家,把 `docs/` 的 16 份文档按类型归位,然后收尾。

### 为什么

- `docs/待办与需求.md` 是流水账,不是规格。2026 年的共识是
  **意图(spec)才是源头,代码是产物**——因为 agent 很会写代码,很不会猜你想要什么。
- Diátaxis:文档只有四类,由「行动 vs 知识」和「学习 vs 工作」两轴生成。
  **混类是绝大多数文档问题的根源**,而当前 `docs/` 是平铺的 16 份混合物。

### 步骤

1. **建 `specs/`**:一份模板(要解决什么问题 / 判据 / 不做什么 / 验收标准)+ README 说明流程:
   先写 spec → 再实现 → 实现后把 spec 转成 `docs/explain/` 的决策记录。
   把 `docs/待办与需求.md` 里**还没做且方向明确**的条目转成 spec,其余留原处。
2. **`docs/` 分四类**(纯移动 + 改引用,低风险):
   - `docs/explain/` — 架构宪法、对标报告、正文数据关联_方向说明、架构重构_v2总体设计
   - `docs/howto/` — 代码规范、两台机器的分工、测试端与阶段3路线
   - `docs/reference/` — 数据契约、API_verified、演进规划与模块地图、架构总览、block.toml 格式
   - `docs/incidents/` — 踩坑记录
   - **保持原地**:变更记录(是日志不是文档)、待办与需求
   ⚠ **移动后必须 `grep -rn "docs/"` 全项目修引用**,包括各 `CLAUDE.md`、rules、skills、生成器、面板。
3. **踩坑自动切片**:写一个生成器,从 `docs/incidents/踩坑记录.md` 按现象标签
   生成 `.claude/skills/troubleshoot/SKILL.md` 的速查表,**取代现在手写的那份**。
   这是「能生成的绝不手写」的最后一块。
4. **收尾全量验收**(见下),更新 `HANDOVER.md`,在 `AGENTS.md` 更新索引。

### 验收(本窗是终验,要全跑)

- `python -m pytest -q` 全过
- `python 平台管理/health_check.py --offline` 0 失败
- `python 平台管理/交接.py` 后所有自动区块正确
- 面板能打开、`python MCP服务/selftest.py` 全过
- 全项目 `grep -rn "docs/"` 无失效引用
- `AGENTS.md` 仍 <200 行

### 收尾

台账全部打勾 → `docs/变更记录.md` 写一条总结 → commit。
告诉用户重构完成,并列出**他需要在 B 机做的事**(见下一节)。

---

## 四、明确不做(任何一窗都不许碰)

1. **不引编排框架**(LangGraph / Temporal):`pipelines` + `core.jobs` 已覆盖断点续跑。
   等出现**真循环**(模型自己决定何时停)再谈。
2. **不做 `plugin.json` / Agent Plugins 打包**:该标准 2026-08-06 才发布,
   启动客户端名单里**没有 Claude Code**。目录布局往它靠,但不绑定。
3. **不做 `workflow_data/` 三层重命名**(raw/curated/serving)。
   收益是命名整齐,代价是**跨机器数据迁移**——权威副本在 B 机,3000+ 文件。
   而 `docs/数据契约.md` 已有等价的「可再生 / 不可再生」分层。**不划算,不做。**
4. **不做多用户 / Web 部署**:会同时推翻「单机」「Zotero 本地 API」「系统凭据库」三条假设。
5. **不物理搬迁中文文件夹、不重命名四环**(见铁律 1、2)。
6. **不把 `docs/` 内容复制进 rules 或 skill**:引用或生成,不复制。

---

## 五、重构完成后需要用户在 B 机做的事(W7 结束时告诉他)

- 双击一次 `更新平台.bat`(拉新代码 **+ 重启常驻进程**)。
  ⚠ 只 `git pull` 不重启没用——面板和 watcher 是长驻进程,会一直跑旧代码。
- 在面板里确认服务状态正常。
- 继续攒精读评测集(Zotero 打「读完」标签 → 面板「精读评价」),这是 W6 留下的唯一人工缺口。
