# -*- coding: utf-8 -*-
"""host.mcp —— MCP 协议层：把平台的能力暴露给 agent。

    server          ★ 服务入口：聚合各 tools/<t>/mcp.py，启动 stdio 服务
    registry        工具清单：读 tools/*/tool.toml，挂上它的 mcp.py，并校验自洽
    stdio           手写的极简 MCP stdio 服务端（零第三方依赖，支持 tool/resource/prompt）
    selftest        协议层离线自测

R4 窗（2026-08-31）把 `zotero_server.py` 解散了：它手写的 10 个工具里，
9 个只读查询进了新的 `tools/library/`，`ping` 留在 `server.py`（那是服务自己的存活检查）。
从此**服务端不知道有哪些工具** —— 加能力只需新建一个 tools/<名>/ 文件夹。
"""
