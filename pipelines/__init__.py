# -*- coding: utf-8 -*-
"""pipelines —— **搬家途中的临时住户**（R3 窗拆完即删，见 REBUILD.md 第四节）。

重构后的组织原则是「按工具切片」：一个工具 = 一个自包含的包，住在 `tools/`。
这个包里剩下的四块还没找到它们该去的工具：

    query_expand     → tools/ask      （问题 → LLM → 多个检索式）
    lib_match        → tools/ask      （向量检索 + 排序判定）
    paper_discovery  → tools/discover （外部检索 + 库内匹配）
    direction_map    → tools/direction（方向地图 / 选题）

R2 窗（2026-08-30）已经搬走的：
    deepread → tools/deepread · extract → tools/extract
    paper_db → tools/paperdb · chart_digitize → tools/digitize

**别往这里加新东西。** 新能力直接建 `tools/<name>/`。
"""
