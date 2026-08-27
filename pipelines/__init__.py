# -*- coding: utf-8 -*-
"""pipelines —— 编排环：宪法里的「定理」，由公理组合而成的能力。

判据：**它本身不解决任何原子问题，只负责「按什么顺序调用谁」**。
需求一变它就变，这很正常 —— 这一环本来就是易变的，
所以要把它压在稳定的 core / domain / adapters 之上，而不是相反。

可以 import：core、domain、adapters、以及别的 pipeline。
不许 import：apps（界面层）。

阶段 2 先迁入四块本来就是「组合」的能力（它们此前混在公理层里，
但都不满足公理的定义 ——「还能被拆成先做 A 再做 B」的就不是公理）：
    chart_digitize   图 → LLM 读图 → 数据点（宪法明确说它是「独立定理」）
    query_expand     问题 → LLM → 多个检索式
    paper_discovery  外部检索 + 库内匹配
    lib_match        向量检索 + 排序判定

阶段 3 会把精读、抽取、问答等主线工作流也做成这里的函数
（现在它们还是靠 subprocess 互相拉起来的脚本）。
"""
