# tools/ask · 库内问答 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。

## 这块是什么

**向用户自己的文献库提问 → 从向量库检索片段 → 大模型结合片段用中文作答 → 附来源。**

**答案只允许基于检索到的片段**（提示词里写死了这条）。
模型不许用自己的知识补充 —— 本工具的价值在于可追溯。

用户是材料方向研究者（聚硼硅氧烷/动态键弹性体），**不懂编程**。

## 什么时候别用它

- 问「全世界有没有人做过 XX」→ 用 `tools/askworld`（库里没有的它答不了）
- 想找**新**文献补库 → 用 `tools/discover`
- 想发散讨论方向、找空白 → 用 `tools/direction`（brainstorm）

## 文件

| 文件 | 干什么 |
|---|---|
| `__init__.py` | 问答编排：检索 → 拼片段 → 作答 → 带回来源 |
| `cli.py` | 命令行入口（`python -m tools.ask "问题"`，无参数进交互模式）|
| `__main__.py` | 一行壳，转给 `cli.main()` |
| `tool.toml` | 工具清单（expose / 花不花钱 / 有什么副作用）—— MCP 服务照它挂 |
| `mcp.py` | 给 agent 的 MCP 面（只做参数转换，不许有逻辑）|
| `README.md` · `SKILL.md` | 给人的说明 · 给 agent 的手册（含**什么时候别用我**）|
| `prompts/` | 系统提示词（`<名>_v<N>.txt`）。**只增不改**：改措辞就新建下一版，旧版留着 |
| `evals/` | 评测：可追溯性（每段带出处、来源不多不少、库空不硬答）。**答案质量那一半还缺**，要你出题 |
| `vectorize.py` | 两条向量化线：精层（精读产物）/ 粗层（Zotero 全文索引）|
| `selftest.py` | 离线自测（不调 LLM、不连 Ollama、不碰真实数据）|

## 为什么向量化在这个工具里

它是问答的前置，不是独立能力 —— 没有向量库，问答只能回答「库是空的」。
两者一起改、一起测才不会脱节（改了切块策略却忘了重建向量库，问答会静悄悄变差）。

**两条线，同一个向量库**（对称于结构化抽取的粗细两层）：

| 线 | 料 | 覆盖 | 谁跑 |
|---|---|---|---|
| 精层 `deep_all()` | 精读产物 `parsed/full.md` | 只有精读过的 | 手动 `--deep` |
| 粗层 `light_all()` | Zotero 自带全文索引 | **全库** | 定时任务每小时（`host.autosync`）|

## 对外接口

```python
from tools import ask

ask.ask_answer('我库里关于剪切增稠有什么')   # → {'answer','sources','chunks'}（不打印）
ask.ask('...')                                # 命令行用：调上面那个并打印
ask.count()                                   # 向量库现在有多少块

from tools.ask import vectorize
vectorize.light_all()      # 粗层增量（定时任务跑的就是这条）
vectorize.deep_all()       # 精层增量
```

`ask_answer` **返回**而不是打印 —— 面板、MCP、命令行共用同一份逻辑。

## 想改什么，去哪改

| 你想改 | 改哪 |
|---|---|
| 用哪个模型作答 | 控制面板的 `ASK_MODEL`（别在代码里写模型名，红线 #3）|
| 检索几块 | `TOP_K`（本文件）|
| 切块策略 | `shared/adapters/embed.chunk` —— **改完要重建向量库** |
| 换向量库 | `shared/adapters/vectordb`（这里一行不用动）|
| 读写路径 | `shared/kernel/paths`（不要手拼 `data/` 的路径，守卫会拦）|

## 怎么验证

```
python tools/ask/selftest.py                  # 7 条，全离线
python host/doctor/health_check.py --offline  # 离线体检，必须全绿
python -m tools.ask "我的库里关于自修复有什么"   # 真问一次（要 Ollama + DEEPSEEK_KEY）
```
