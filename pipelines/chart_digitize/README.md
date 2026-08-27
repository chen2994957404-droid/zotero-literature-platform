# chart_digitize · 图表数字化基础件（公理层）

**公理**：图表图片 → 数据点（X-Y 数值）。把论文图里的曲线/散点抠成可用数值，
解决"定量数据收集"痛点。

## 接口
```python
from pipelines.chart_digitize import digitize

r = digitize(image_b64)                          # 默认视觉 provider
r = digitize(image_b64, provider='ollama', model='qwen2.5vl:7b')  # 本地零成本
# → {chart_type, x_axis, y_axis, series:[{name, points:[[x,y]...]}], confidence, note}
#   或 {error: ...}
```
常配合 figure_crop 用：先 crop_figures 裁图，再 digitize 每张。

## 技术路线（对标结论）
用**视觉大模型**（VLM），不用传统 OpenCV。依据 PlotPick（2026, arXiv:2605.06021）：
VLM 提取准确率 88-96% vs 专用模型 71%，且对没见过的图类型稳定。
代码是我们自己的干净实现（借鉴思路，非 copy 重依赖），复用 llm_client 的视觉能力。

## 成本策略（大规模友好）
- **本地视觉模型**（qwen2.5vl:7b，Ollama）：零 API 成本，适合几万篇批量粗提取。
- **云端视觉模型**（通义千问 qwen-vl 等）：少数关键图要高精度时用。
- 底层可换、上层不动：只改 provider/model 参数。见 docs/视觉模型选择_参考.md。

## 输出语言
英文（图表数据是给 LLM/机器用的原生数据，不翻译）。

## 依赖
仅 llm_client（其视觉能力）。需一个视觉模型（本地 Ollama 或云端）。

## 自测
```
python pipelines/chart_digitize/selftest.py
```
用本地 qwen2.5vl + 一张已解析文献的图，验证 digitize 返回结构正确。

## 质量说明
本地 7B 读的是"合理采样点"（找趋势/粗筛够用）；精确逐点数字化需更强模型。
接口已支持换模型，按需升级。
