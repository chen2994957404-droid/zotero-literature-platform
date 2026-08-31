# -*- coding: utf-8 -*-
"""digitize · 图表数字化：论文图里的曲线/散点/柱状图 → 可用的 X-Y 数值。

职责：把论文里的曲线/散点/柱状图，用视觉大模型提取成结构化数据点（X-Y 数值）。
解决"定量数据收集"痛点——把别人图里的数据抠出来变成可用数值。

思路借鉴 PlotPick（2026，arXiv:2605.06021，证明 VLM 提取超越专用模型 88-96% vs 71%），
但代码是我们自己的干净实现，无外部重依赖（不用 OpenCV，复用 llm_client 视觉能力）。

只做「图片 → 数据点」一件事。底层视觉模型可换（云/本地），接口不变。

**对外契约**（别的地方只许调这个；`cli.py` / `mcp.py` 也只许调这个）：

| 入口 | 干什么 |
|---|---|
| `digitize(image_b64, hint='', provider, model, key) → dict` | 一张图 → `{chart_type, x_axis, y_axis, series, confidence, note}`，读不出时 `{'error': ...}` |

⚠ **必须用云端大模型**：本地 7B 视觉模型会**编出看似合理的假数据**
（宪法零号判据的反面教材 —— 编的数字最像事实）。

配置：视觉模型经 llm_client 的 chat_vision，走 VISION_PROVIDER/DEEPSEEK_VISION_MODEL 等。
成本策略：先用云端验证效果；后接本地视觉模型（OLLAMA_VISION_MODEL）实现零成本大规模。
"""
import os, sys
from shared.adapters.llm_client import chat_vision, _parse_json_lenient, LLMError

# All-English prompt (chart data is native machine data for downstream LLM/analysis).
_SYS = (
    "You are a scientific chart digitization engine. Given a figure from a paper "
    "(line/scatter/bar/box plot, etc.), read out its data precisely. Rely strictly on "
    "what is visible in the image; do not fabricate. First identify the axes (labels, units, "
    "tick range, whether log-scale), then read each data series point by point. "
    "Output exactly one JSON, no explanation, no code fences."
)

_USER_TMPL = (
    "Digitize this chart and output JSON with this structure:\n"
    "{{\n"
    '  "chart_type": "line/scatter/bar/box/...",\n'
    '  "x_axis": {{"label": "", "unit": "", "min": number, "max": number, "log": false}},\n'
    '  "y_axis": {{"label": "", "unit": "", "min": number, "max": number, "log": false}},\n'
    '  "series": [{{"name": "series name/legend", "points": [[x1,y1],[x2,y2],...]}}],\n'
    '  "confidence": "high/medium/low",\n'
    '  "note": "uncertainty notes when reading"\n'
    "}}\n"
    "Requirements: values in real chart coordinates (not pixels); use null for axis info you "
    "cannot find; for dense curves, sample representative points at reasonable intervals; if data "
    "cannot be read, leave series empty and explain in note.\n{hint}"
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
