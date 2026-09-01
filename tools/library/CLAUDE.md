# tools/library · 查我的 Zotero 库 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。
> 用户是材料方向研究者（聚硼硅氧烷/动态键弹性体），**不懂编程**。

## 这个工具是什么

**Zotero 库的只读门面**：搜条目、看合集标签、拿正文 PDF 路径与全文文本。

它是整个平台里**唯一一个 agent 可以随便调的工具切片** —— 全部只读、全部免费。
别的工具要么花钱（大模型）要么改数据（写 Zotero），所以它们在 MCP 上都是 prompt，
只有本工具和 `paperdb` 是 tool。

## 文件

| 文件 | 干什么 |
|---|---|
| `__init__.py` | 查 + 渲染。查的部分全是转发给适配层，渲染部分是纯字符串 |
| `cli.py` | 人的命令行入口（`python -m tools.library <动作>`）|
| `mcp.py` | 9 个只读 MCP 工具（只做参数转换）|
| `tool.toml` | 工具清单：`expose="tool"`、不花钱、无副作用 |
| `selftest.py` | 离线自测：只测渲染与「最近 N 天」的判断 |
| `evals/` | 评测：检索的**不变量**（用自己的标题能搜到自己等）。要真实 Zotero，`pytest -m live` 才跑 |

## 它的来历（R4 窗，2026-08-31）

原来是 `host/mcp/zotero_server.py` 里手写的 10 个 MCP 工具。R4 窗把它解散：

- 9 个只读查询 → 本工具
- `ping` → 留在 `host/mcp/server.py`（那是服务自己的存活检查，不是一个能力）
- 拼 Zotero API 路径、读 `Total-Results` 响应头、压平条目 →
  **下沉进 `shared/adapters/zotero_client`**（那是外部世界的形状，只该有一处知道）

**为什么单独成工具，而不是并进 `ask`**（REBUILD.md 第四节留了这个选择）：
`ask` 要调付费大模型，按 R4 判据只能暴露成 prompt（由人点）。
把这些免费只读的查询塞进去，它们会跟着降级成 prompt，
agent 就再也不能自己检索文献库了 —— 那是实打实的功能倒退。**判据优先于映射表。**

## 一行网络代码都没有

本工具只 import `shared.adapters.zotero_client`。Zotero API 长什么样、
路径怎么拼、响应是什么形状，只有适配层知道。
这是「换掉 Zotero 只改一个文件」的保证，架构守卫会强制。

想加一个新查询：**先在 `zotero_client` 里加一个函数**，本工具再调它。
别在这里拼 `/users/<id>/...` 字符串。

## 渲染为什么在这里

`render_items` / `render_item` / `render_collections` / `render_tags` 是纯字符串函数。
放在 `__init__.py` 而不是 `mcp.py`，是因为命令行和 MCP 要用同一份排版 ——
`mcp.py` 只许做参数转换，不许有逻辑。

## 边界

- **只读**。没有任何写操作。要改库房去 `tools/curate`（那边每一步都先预览）
- Zotero 本地 API 只监听 localhost：**只有主力机跑得通**，编程端连不上是预期的，
  所以 `stats()` 返回 `zotero_reachable=False` 而不是抛异常
- `fulltext()` 给的是 Zotero 自带的全文索引：**没有版面、没有图、公式常是乱的**。
  要像样的全文去 `library/<KEY>/parsed/full.md`（精读产物）

## 改完怎么验证

```
python tools/library/selftest.py              # 本工具自测（离线）
python host/mcp/server.py --list              # 工具面还在不在、清单自不自洽
python -m tools.library stats                 # 真连一次（要 Zotero 开着，主力机）
python host/doctor/health_check.py --offline  # 离线体检，必须全绿
```
