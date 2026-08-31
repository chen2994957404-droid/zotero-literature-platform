# host/mcp · 把平台能力包成 agent 可调用的 MCP

> 你可能是被单独选中这个文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这是什么

**平台对外的 MCP 接口层**（宪法里的「界面层」）：让 Claude Code / Cursor / DSH 等 agent
通过标准协议直接调用平台能力。

R4 窗（2026-08-31）改成**聚合**：服务端自己不知道有哪些工具，
它去 `tools/*/tool.toml` 现读现挂。加一个能力 = 新建一个 `tools/<名>/` 文件夹，
**这个文件夹一个字都不用改**。此前是 `zotero_server.py` 里手写 10 个工具的注册表，
加一个能力要改三处，于是没人加。

## 各文件职责

| 文件 | 干什么 |
|---|---|
| `server.py` | ★ 服务入口。挂 `ping`，然后让 registry 把各工具挂上；`--list` 给人看清单 |
| `registry.py` | 读 `tools/*/tool.toml`、import 各 `tools/<t>/mcp.py` 调 `register(server)`、校验自洽 |
| `stdio.py` | 手写 MCP stdio 协议层（JSON-RPC 2.0 + 换行分隔，零第三方依赖）|
| `selftest.py` | 协议层离线自测（不联网、不依赖用户数据）|

为什么不用官方 SDK：平台「少依赖」宪法 + 协议已实测稳定（官方 SDK 的 ReadBuffer
就是按 `\n` 切帧，序列化 = `JSON + '\n'`）；日后要接 SSE/HTTP 再换 SDK，本层接口不变。

## 三类暴露 —— 这就是安全边界

| 类 | 谁能触发 | 判据 |
|---|---|---|
| `tool` | **模型可以自己调** | 只读且免费 |
| `resource` | 模型可以自己读 | 只读数据（对比表这种）|
| `prompt` | **人在客户端里点** | 花钱的、有副作用的一律走这里 |

**一条铁律，`registry.check()` 强制**：
`costs_money=true` 或 `side_effects` 非空的工具切片，**不许注册 tool 类**。
钱和副作用必须停在人这一侧。故意违反会让 `--list` 变红、自测变红。

现状：`library`（9 个）与 `paperdb`（4 个）是 tool；`extract` 出 3 份 resource；
其余 8 个切片各出 1 条 prompt。

## 协议实现到什么程度

`initialize` / `ping` / `tools/list` / `tools/call` /
`resources/list` / `resources/templates/list` / `resources/read` /
`prompts/list` / `prompts/get`。

resource 与 prompt 的报文形状**核对过官方 schema `2024-11-05`**（R4 窗，
`modelcontextprotocol/modelcontextprotocol` 仓库的 `schema/2024-11-05/schema.ts`）：
- `resources/read` → `{'contents': [{uri, mimeType, text}]}`
- `prompts/get` → `{'description', 'messages': [{role, content:{type:'text', text}}]}`
- 能力声明 `resources: {subscribe, listChanged}` / `prompts: {listChanged}`，
  **只声明真的注册了的**（声明了却没有，某些客户端会一直转圈等列表）

## 启动方式（给 MCP 客户端配）

```
command: python
args: [ <项目根>/host/mcp/server.py ]
```

人看工具清单：`python host/mcp/server.py --list`

Claude Code（`--scope user` = 全局生效）：
```
claude mcp add zotero --scope user -- python "<项目根>\host\mcp\server.py"
```
Codex CLI（`~/.codex/config.toml`）：
```toml
[mcp_servers.zotero]
command = "python"
args = ["<项目根>\\host\\mcp\\server.py"]
```
若某客户端握手报协议版本不兼容：改 `stdio.py` 顶部 `PROTOCOL_VERSION` 一行。
多客户端可同时连接（各起独立进程）。

⚠ **B 机（主力机）上的现有配置指向的是老路径 `MCP服务/zotero_server.py`，
工具名也变了**（`search_items` → `library_search`）。合并回 main 时要重新注册 ——
这件事记在 REBUILD.md R7 窗的交接项里。

## 写操作留给谁

MCP 面**不做写操作**：写 Zotero 的能力（打标签/改名/去重/回写附件）都在
`tools/curate` 与 `tools/deepread` 里，它们在 MCP 上是 prompt，
由人点、由人确认，并且各自带机器角色守卫。绕过 proc_lock 的写是事故。

## 改完必须做

```
python host/mcp/selftest.py                   # 协议层自测，必须全过
python host/mcp/server.py --list              # 清单必须自洽（末尾那行是 ✓）
python host/doctor/health_check.py --offline  # 全局离线体检
python host/codegen/handover.py               # 刷新 CLAUDE.md 结构树 / HANDOVER.md
```
改动记 `docs/变更记录.md`，新坑记 `docs/incidents/踩坑记录.md`，**git commit**。
