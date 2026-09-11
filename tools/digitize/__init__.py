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
| `digitize_file(path, hint='', ...) → dict` | 同上，但直接给图片文件路径（命令行用）|
| `digitize_paper(item_key, only=None, refresh=False, ...) → {图号: dict}` | **一篇已解析文献 → 每张图的数值**（自己裁图、自动落盘、抠过的不重抠）|
| `load_curves(item_key)` / `save_curves(item_key, results)` | 读/存这篇抠过的曲线（`curated/<key>/curves.json`）|

⚠ **必须用云端大模型**：本地 7B 视觉模型会**编出看似合理的假数据**
（架构准则调研先行原则的反面教材 —— 编的数字最像事实）。

配置：视觉模型经 llm_client 的 chat_vision，走 VISION_PROVIDER/DEEPSEEK_VISION_MODEL 等。
成本策略：先用云端验证效果；后接本地视觉模型（OLLAMA_VISION_MODEL）实现零成本大规模。
"""
import os, sys
from shared.adapters.llm_client import chat_vision, _parse_json_lenient, LLMError
from shared.kernel import prompts

# All-English prompt (chart data is native machine data for downstream LLM/analysis).
_SYS = prompts.load('digitize', 'main@v1')

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
        # 走「图表数字化」用途的通道；哪个视觉模型是**配置**（路由表里），不是这里的默认值。
        # 调用方显式给了 model 就用它，否则用路由表配的。
        out = chat_vision(_SYS, user, image_b64, purpose='DIGITIZE', model=model,
                          temperature=0.1, json_mode=True)
    except LLMError as e:
        return {'error': str(e)}
    except Exception as e:
        return {'error': f'视觉模型调用失败: {e}'}
    try:
        return _parse_json_lenient(out)
    except Exception:
        return {'error': '视觉模型输出无法解析为 JSON', 'raw': out[:300]}


def digitize_file(path, hint='', provider=None, model=None, key=None):
    """同 `digitize`，但直接收图片文件路径（命令行/面板用，省得调用方自己 base64）。"""
    import base64
    try:
        with open(path, 'rb') as fh:
            b64 = base64.b64encode(fh.read()).decode('ascii')
    except OSError as e:
        return {'error': f'读不了图片文件：{e}'}
    return digitize(b64, hint=hint, provider=provider, model=model, key=key)


def digitize_paper(item_key, only=None, hint='', provider=None, model=None,
                   key=None, refresh=False):
    """**一篇已解析文献 → 它每张图的数值**（`{图号: 结果}`）。

    此前只有「给我一张图片文件」这个入口，而用户手里从来不是图片文件 ——
    是一篇 Zotero 里的文献。中间那步「从解析产物里把 Figure 裁出来」
    写在 README 和 MCP 提示词里让**调用方自己做**，等于把最容易做错的一步
    （踩坑 #7 的全部智慧都在 `figure_crop` 里）留给了别人。

    `only` 给图号列表就只做那几张（`[2, 3]`）；不给就整篇。
    **每张图都要调一次云端视觉模型，整篇是要花钱的**，所以 `only` 是常用参数。

    **抠过的图不再重抠**：结果存在 `curated/<key>/curves.json`，
    下次直接拿来用（`refresh=True` 才强制重读）。抠出来的数值同时会被
    `tools/paperdb` 收进测量层，跟文字里抽的数字放在一起比大小。

    返回 `{图号: {chart_type, series, ...}}`；某张读不出来时那一项是 `{'error': ...}`，
    不影响别的图 —— 与 `digitize()` 同一个契约。
    **没图就返回 `{}`，不抛异常**：无论是「这篇没有曲线图」还是「这篇还没解析」，
    对调用方都是同一件事（这次没东西可做），而 `digitize()` 一族的契约是不抛异常。
    """
    from shared.kernel import paths
    from shared.domain.figure_crop import crop_figures

    try:
        figs = crop_figures(paths.parsed_dir(item_key))
    except (OSError, paths.BadKeyError):
        return {}
    cached = load_curves(item_key)
    out = {}
    for f in figs:
        num = f.get('num')
        if only and num not in only:
            continue
        if not refresh and str(num) in cached:
            out[num] = cached[str(num)]      # 这张图上次已经花钱读过了
            continue
        r = digitize(f['b64'], hint=hint, provider=provider, model=model, key=key)
        r['caption'] = f.get('caption', '')
        out[num] = r
    save_curves(item_key, out)
    return out


# ── 抠出来的数值要留住 ────────────────────────────────────────────────
# 为什么（2026-09-06）：此前读完图把结果返回给调用方就完了，**谁也没存**。
# 于是同一张图每问一次就要再花一次云端视觉模型的钱，抠出来的数值也进不了查询库。
# 图只需读一次，数值该跟精读产物一样长期留着 —— 真相是文件，库只是索引。
def load_curves(item_key):
    """这篇已经抠过的曲线：`{图号: 结果}`；没有就 `{}`（不抛异常）。"""
    import io
    import json
    from shared.kernel import paths
    try:
        p = paths.curves(item_key)
    except paths.BadKeyError:
        return {}
    if not os.path.exists(p):
        return {}
    try:
        d = json.load(io.open(p, encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}          # 坏文件不该让整条线挂掉，当作还没抠过


def save_curves(item_key, results):
    """把这次抠到的图**并进**已有的 curves.json，返回落盘路径。

    **并入而不是覆盖**：一次常常只读一两张图（`only=[2,3]`），
    覆盖会把上次花钱读出来的其它图抹掉。读失败的那张（`{'error': ...}`）不存 ——
    存了会让「这张图抠过了」变成假的。
    """
    import io
    import json
    from shared.kernel import paths
    keep = {str(k): v for k, v in (results or {}).items()
            if isinstance(v, dict) and not v.get('error')}
    if not keep:
        return ''
    merged = load_curves(item_key)
    merged.update(keep)
    p = paths.curves(item_key)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(merged, io.open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    return p
