# tools/library · 查证据库 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。
> 用户是材料方向研究者（聚硼硅氧烷/动态键弹性体），**不懂编程**。

## 这个工具是什么

**证据库的只读门面**：有没有这篇、手上有什么、库内向量检索、骨架菜单与按节取原文、
参考文献、单元库；以及按条件检索（DOI / 标题词 / 作者 / 通讯 / 团队…）和研究团队。

它是平台里**模型可以随便调的工具包**之一 —— 全部只读、全部免费。
别的工具要么花钱（大模型）要么改数据，所以它们在 MCP 上都是 prompt。

**2026-10-13 Zotero 移出平台**：这里原来一半是「查 Zotero」（搜条目、合集、标签、最近、PDF 路径、全文索引），
连同 `shared/adapters/zotero_client` 一起删了。旧代码在 git 标签 `zotero-before-removal`。

## 文件

| 文件 | 干什么 |
|---|---|
| `__init__.py` | 证据库：`db_*`、`retrieve`、`refs`、`outline` / `section`、`units` + 渲染 |
| `dbsearch.py` | 检索：`find()`（DOI / 标题词 / 作者 / 通讯 / 团队 / 年份 / 期刊 / 有无正文 SI 精读）、`detail()`（一篇的完整卡片）|
| `oaindex.py` | 作者 + 摘要索引（OpenAlex 取一次，存 `serving/oa_index.json`，可重建）|
| `teams.py` | 研究团队：名单（`state/teams.json`，人工查证）× 作者索引 → 文章挂到团队（`serving/team_links.json`）|
| `census.py` | 盘点：证据库里有什么 |
| `cli.py` | 人的命令行入口（`python -m tools.library <动作>`）|
| `mcp.py` | 只读 MCP 工具（只做参数转换）|
| `tool.toml` | 工具清单：`expose="tool"`、不花钱、无副作用 |
| `selftest.py` | 离线自测：渲染与检索的纯逻辑 |
| `evals/` | 评测：检索的**不变量**（用自己的标题能搜到自己等）。要真实证据库数据，`pytest -m live` 才跑 |

## 渲染为什么在这里

`render_*` 是纯字符串函数。放在 `__init__.py` 而不是 `mcp.py`，是因为命令行和 MCP 要用同一份排版 ——
`mcp.py` 只许做参数转换，不许有逻辑。文献库应用（`host/app`）也直接调本工具的函数，不另写逻辑。

## 边界

- **只读**。「检索 --建索引」「团队 --重建」只写可重建的索引
- 旧的 8 位编号（老 Zotero 编号）在入口处经 `catalog.resolve` 换成现在的 doi_… 编号

## 改完怎么验证

```
python tools/library/selftest.py              # 本工具自测（离线）
python -m pytest -q tools/library/tests       # 离线测试（检索、团队）
python host/mcp/server.py --list              # 工具面还在不在、清单自不自洽
python host/doctor/health_check.py --offline  # 离线体检，必须全绿
```
