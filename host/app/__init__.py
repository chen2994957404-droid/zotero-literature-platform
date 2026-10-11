# -*- coding: utf-8 -*-
"""host.app · 文献库应用（2026-10-11 起）：直连证据库的独立应用，**不是控制面板**。

用户定（2026-10-11）：单独做，以后做大成功能完善的客户端；技术路线 FastAPI 后台 + Vue 3 前台。
第一版只有检索页。

| 部分 | 在哪 |
|---|---|
| 后台（只把工具层能力开成 HTTP 接口 + 托管前台）| `server.py` |
| 前台（Vue 3 + Vite，打包产物 `web/dist/` 不进版本库）| `web/` |

业务逻辑不写在这里：检索与文献卡片 `tools.library.dbsearch`，团队 `tools.library.teams`。
"""
