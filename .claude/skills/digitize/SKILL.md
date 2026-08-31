---
name: digitize
description: 论文图表图片 → 可用的 X-Y 数值。什么时候用：用户说「把这张图里的曲线变成数据」「这条应力应变曲线的数值给我」；你已经有一张图片文件（曲线图/散点图/柱状图/箱线图）
---

<!-- 本文件由 host/codegen/skills.py 生成，**别手改**。改源：tools/digitize/SKILL.md + tools/digitize/tool.toml -->

> **动手之前先看这三行**（取自 `tools/digitize/tool.toml`）：
> **会花钱** · 无副作用（只读） · 任何机器都能跑
> MCP 暴露方式：`prompt`（**由人在客户端点，模型不能自己发起**）
> 命令行：`python -m tools.digitize`

# digitize —— 把论文图里的曲线读成数值

## 什么时候用我

- 用户说「把这张图里的曲线变成数据」「这条应力应变曲线的数值给我」
- 你已经有一张**图片文件**（曲线图/散点图/柱状图/箱线图）

## 怎么用

我是 **prompt**（要云端视觉大模型）。讲清代价、用户点头后：

```
python -m tools.digitize "<图片路径>" [--hint "只读红色那条曲线"]
```

输出 JSON：`chart_type / x_axis / y_axis / series[{name, points}] / confidence / note`。

要先从 PDF 里把图裁出来 → 用 `shared.domain.figure_crop`；
精读过的文献，图已经裁好在 `library/<KEY>/parsed/images/`。

## 什么时候**别**用我

- **图里的数字文章正文已经写了** → 直接从 `library_fulltext` 或精读报告里读，
  比让视觉模型看图准得多，还免费
- **要的是趋势描述而不是数值** → 让模型直接看图说话即可，不必走数字化
- **想省钱用本地 7B** → **不行**。实测它把 FTIR 光谱读成完美等差数列，
  还标 `confidence=high`。编的数字最像事实，也最难被发现。
  `--provider ollama` 只用来验证接口通不通，它的数字一个都不能信

## 边界

- 密集曲线是**按合理间隔采样**，不是逐点还原；要精确逐点要更强的模型
- 读不出来时返回 `series` 为空并在 `note` 里说明 —— 那是正确行为，别追问它硬编
- 输出是英文（图表数据是给机器用的原生数据）
