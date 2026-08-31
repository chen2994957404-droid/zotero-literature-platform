# figure_crop · 裁图基础件（公理层）

**公理**：MineRU 解析结果 → 完整 Figure 图片（base64 PNG）。
精读线独有、最复杂的公理（踩坑 #7 花时间最多，智慧全固化于此）。

## 接口
```python
from domain.figure_crop import crop_figures

figs = crop_figures("library/<key>/parsed")
# → [{b64, caption, page, num}, ...]；b64 可直接嵌 HTML <img src=...>
```

## 依赖
PyMuPDF（fitz）。需 parsed 目录含 `layout.json` + `*_origin.pdf`。

## 固化的踩坑 #7（对所有期刊通用，别改坏）
- 用坐标从原 PDF 裁完整图，**不用** MineRU 碎图（子问题A）。
- 用 `layout.json` 的 `page_size` 做缩放基准，bbox 与 PDF 1:1（子问题B）。
- 合并 `image`/`chart`/`table` 三类视觉块——数据图常被标成 chart/table（子问题C）。
- 纵向聚类成 Figure（间隔>页高15%拆分），**不依赖题注**，题注识别失败也不丢图（子问题D）。

## 自测
```
python domain/figure_crop/selftest.py
```
用一篇已解析文献（library 下有 parsed 的）验证能裁出图，且每张图有 b64 数据。
