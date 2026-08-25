# MCP服务 · 把平台能力包成 agent 可调用的 MCP

> 你可能是被单独选中这个文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这是什么

**平台对外的 MCP 接口层**（宪法里的「界面层」）：把平台已有的能力包成
MCP（Model Context Protocol）服务，让 Claude Code / Cursor / DSH 等 agent
通过标准协议直接调用库房能力。

背景决策（2026-08-26，详见 变更记录）：
- 调研了 3 个现成 Zotero MCP（nealcaren/mcp-zotero、alisoroushmd/zotero-mcp、
  drxaibi/zotero-mcp），结论是**库房层「借鉴重写」优于搬运**：
  我们已有 `modules/zotero_client` 这块在真实库上磨出来的公理件，MCP 只是薄壳；
  0-star 仓库搬运后要自己维护，不如自己写壳 + 抄它的 API 细节。
- **分析层（知识图谱/撤稿核查等）明确不做**（用户 2026-08-26 拍板）。

## 职责

- `mcp_stdio.py`：手写 MCP stdio 协议层（JSON-RPC 2.0 + 换行分隔，零第三方依赖）。
  为什么不用官方 SDK：平台「少依赖」宪法 + 协议已实测稳定（官方 SDK 的 ReadBuffer
  就是按 `\n` 切帧，序列化 = `JSON + '\n'`）；日后要接 SSE/HTTP 再换 SDK，本层接口不变。
- `zotero_server.py`：库房层只读工具集，封装 `modules/zotero_client`。
- `selftest.py`：协议层离线自测（不联网、不依赖用户数据）。

## 对外接口（zotero_server 的 MCP 工具，全部只读）

| 工具 | 用途 | 参数 |
|---|---|---|
| `ping` | 存活检查 | — |
| `library_stats` | 库统计 + Zotero 本地 API 是否可达 | — |
| `search_items` | 按词/标签/类型/合集搜索 | query, qmode, tag, itemType, collection, limit, start |
| `get_item` | 单篇完整信息（含正文 PDF 路径） | itemKey |
| `find_pdf` | 定位正文 PDF 本地路径（排除 SI） | itemKey |
| `get_fulltext` | 取正文全文文本 | itemKey, maxChars |
| `list_collections` | 合集树 | — |
| `get_collection_items` | 合集内文献 | collectionKey, limit |
| `list_tags` | 标签及文献数 | — |
| `get_recent_items` | 最近 N 天新增/修改 | days, limit |

启动方式（给 MCP 客户端配）：
```
command: python
args: [ <项目根>/MCP服务/zotero_server.py ]
```
人看工具清单：`python MCP服务/zotero_server.py --list`

## v1 边界（别越界）

- **只读**：本 v1 不写 Zotero 任何数据，与 watcher 无并发冲突。
- **写操作（打标签/改名/去重/清理）留 v2**：届时必须 dry-run + 显式确认参数，
  并与 watcher 的标签状态机（文献精读/）协调，绕过 proc_lock 的写是事故。
- **平台数据资产（summary.html/structured JSON/向量库）不属于本服务**：
  那是「问答/抽取」线的领域，别把 workflow_data 的读取塞进来（保持单一职责）。

## 谁在用它

**已接入 DSH（2026-08-25，HMR 热加载生效）**：DSH 所有 agent 会话可用
`mcp__zotero__*` 只读工具查文献库。接入方式见 `docs/变更记录.md` 2026-08-25 续条目
（改 `C:\Users\Administrator\.dsh\profiles\web\cordis.patch.yml`，serverName=zotero）。
Claude Code / Cursor 等外部客户端也可按「启动方式」自行接入。

### 其他 MCP 客户端接入（2026-08-25 查证，均用绝对路径、不依赖工作目录）

服务端位置由 `__file__` 定位（标准开头向上找 `modules/`），配置读项目根 `.env`，
**agent 在哪个文件夹跑都不影响**。服务为标准 MCP stdio，协议版本 `2024-11-05`。

Claude Code（`--scope user` = 全局生效）：
```
claude mcp add zotero --scope user -- python "D:\02_AI\Projects\zotero-literature-platform\MCP服务\zotero_server.py"
```
或在项目根放 `.mcp.json`：`{"mcpServers": {"zotero": {"command": "python", "args": ["D:/02_AI/Projects/zotero-literature-platform/MCP服务/zotero_server.py"]}}}`

Codex CLI（`~/.codex/config.toml`）：
```toml
[mcp_servers.zotero]
command = "python"
args = ["D:\\02_AI\\Projects\\zotero-literature-platform\\MCP服务\\zotero_server.py"]
```

若某客户端握手报协议版本不兼容：改 `mcp_stdio.py` 顶部 `PROTOCOL_VERSION` 一行。
多客户端可同时连接（各起独立进程，v1 只读无冲突）。

## 改完必须做

```
python MCP服务/selftest.py            # 协议层自测，必须全过
python 平台管理/health_check.py        # 全局体检，确认没碰坏别人
python 平台管理/交接.py                 # 刷新 CLAUDE.md 结构树 / HANDOVER.md
```
改动记 `docs/变更记录.md`，新坑记 `docs/踩坑记录.md`，**git commit**。
