# figure_crop · 裁图

> 你可能是被单独选中这个模块文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这是什么

从 MineRU 的解析结果里裁出**完整的 Figure**（含子图与题注），而不是零散的小图块。
住在 `host/mcp/` 下，因为唯一的用户是给 Claude Science 的 `/science` 接口（下沉规则：只有一个用户就住进那个用户里）。

用户是材料方向研究者（聚硼硅氧烷/动态键弹性体），**不懂编程**。技术决策你自己拿主意，跟他汇报用通俗表述。

## 对外接口

`crop_figures(parsed_dir, ...)` → 图片列表（含 base64、题注、页码、编号）；`shrink_jpeg(path, max_bytes)` 把一张图压到回包放得下。

## 谁在用它

`host/mcp/science.py`：`figure_image`（一张图直接回小 JPEG）与 `paper_files`（图号 → 图片文件对照）。
裁好的图缓存在 `curated/<id>/figures/`，删了下次现裁。

## 固化的踩坑 #7（对所有期刊通用，别改坏）

- 用坐标从原 PDF 裁完整图，**不用** MineRU 碎图。
- 用 `layout.json` 的 `page_size` 做缩放基准，bbox 与 PDF 1:1。
- 合并 `image` / `chart` / `table` 三类视觉块 —— 数据图常被标成 chart/table。
- 纵向聚类成 Figure（间隔 > 页高 15% 拆分），**不依赖题注**，题注识别失败也不丢图。

## 改完必须做

```
python host/mcp/figure_crop/selftest.py
python host/doctor/health_check.py --offline
```
