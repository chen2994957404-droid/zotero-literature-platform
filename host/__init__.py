# -*- coding: utf-8 -*-
"""host —— 平台自身：不是科研能力，是「让平台活着」的那些东西。

跟 `tools/` 的区别是**服务对象**：`tools/` 服务于用户的科研，
`host/` 服务于平台本身（起得来、看得见、更新得动、能被 agent 调用）。

    panel/     控制面板（用户的操作入口，本地网页）
    doctor/    体检 + 诊断报告 + 产物缺口
    deploy/    部署与更新（把代码拉到主力机并重启常驻服务）
    codegen/   所有生成器（HANDOVER.md、.claude/ 等一律生成，不手写）
    mcp/       MCP 协议层（聚合各 tools/<t>/mcp.py 暴露给 agent）

硬规则：**没人 import `host/`；`host/` 可以 import 一切。**
它在依赖图的最上面，所以怎么改都不会波及能力层。
"""
