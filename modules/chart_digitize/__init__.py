# -*- coding: utf-8 -*-
"""chart_digitize · 图表数字化基础件（公理：图表图片 → 数据点）

职责：把论文里的曲线/散点/柱状图，用视觉大模型提取成结构化数据点（X-Y 数值）。
解决"定量数据收集"痛点——把别人图里的数据抠出来变成可用数值。

思路借鉴 PlotPick（2026，arXiv:2605.06021，证明 VLM 提取超越专用模型 88-96% vs 71%），
但代码是我们自己的干净实现，无外部重依赖（不用 OpenCV，复用 llm_client 视觉能力）。

公理特征：只做「图片 → 数据点」一件事。底层视觉模型可换（云/本地），接口不变。

对外接口：
  - digitize(image_b64, hint='') → dict（含 axes/series/points，或 error）

配置：视觉模型经 llm_client 的 chat_vision，走 VISION_PROVIDER/DEEPSEEK_VISION_MODEL 等。
成本策略：先用云端验证效果；后接本地视觉模型（OLLAMA_VISION_MODEL）实现零成本大规模。
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from modules.llm_client import chat_vision, _parse_json_lenient, LLMError

_SYS = (
    "你是科研图表数字化引擎。给你一张论文里的图表（曲线图/散点图/柱状图等），"
    "你要精确读出其中的数据。严格只依据图片可见内容，不编造。"
    "先识别坐标轴（轴标签、单位、刻度范围、是否对数轴），再逐条读出每个数据系列的点。"
    "只输出一个 JSON，不要解释、不要代码围栏。"
)

_USER_TMPL = (
    "请数字化这张图表，输出 JSON，结构：\n"
    "{{\n"
    '  "chart_type": "line/scatter/bar/box/...",\n'
    '  "x_axis": {{"label": "", "unit": "", "min": 数值, "max": 数值, "log": false}},\n'
    '  "y_axis": {{"label": "", "unit": "", "min": 数值, "max": 数值, "log": false}},\n'
    '  "series": [{{"name": "系列名/图例", "points": [[x1,y1],[x2,y2],...]}}],\n'
    '  "confidence": "high/medium/low",\n'
    '  "note": "读数时的不确定性说明"\n'
    "}}\n"
    "要求：数值用图上真实坐标（不是像素）；找不到的轴信息填 null；"
    "曲线密集时按合理间隔采样代表性点；无法读出数据则 series 为空并在 note 说明。\n{hint}"
)


def digitize(image_b64, hint='', provider=None, model=None, key=None):
    """图表图片 → 数据点 dict。hint 可给额外提示（如"只读红色曲线"）。

    返回 dict（chart_type/x_axis/y_axis/series/confidence/note），
    或 {'error': ...} 当无法解析。
    """
    user = _USER_TMPL.format(hint=('额外提示：' + hint) if hint else '')
    try:
        out = chat_vision(_SYS, user, image_b64, provider=provider, model=model,
                          key=key, temperature=0.1, json_mode=True)
    except LLMError as e:
        return {'error': str(e)}
    except Exception as e:
        return {'error': f'视觉模型调用失败: {e}'}
    try:
        return _parse_json_lenient(out)
    except Exception:
        return {'error': '视觉模型输出无法解析为 JSON', 'raw': out[:300]}
