# -*- coding: utf-8 -*-
"""tools —— 工具切片：一个工具 = 一个自包含的包。

组织原则是**按工具切，不按技术分层切**：一个工具的代码、MCP 暴露、
skill、提示词、评测、测试、文档全在它自己的文件夹里。
这样优化任何一个工具时，只需要打开一个文件夹。

硬规则：**`tools/*` 不许 import 别的 `tools/*`。** 要共用就下沉到 `shared/`，
而下沉的门槛是「被 ≥2 个工具用到」。

每个 `tools/<name>/` 形状固定（守卫强制）：
    tool.toml  __init__.py  cli.py  mcp.py
    SKILL.md   README.md    INCIDENTS.md
    prompts/   evals/       tests/
"""
