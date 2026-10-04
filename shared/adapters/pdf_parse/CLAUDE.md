# pdf_parse · PDF 解析

> 你可能是被单独选中这个模块文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这是什么

**一个原子模块** —— 平台的最小可复用单元。整个项目的架构是：
原子模块（原子能力）→ 工作流（工作流）→ 组合。你现在在最底层。

**原子模块的特征：只做一件不可再分的事。** 如果你想在这里加一个「顺便还做 XX」的功能，
那说明 XX 属于上层，不属于这里。保持这块的纯粹，是整个体系不腐坏的前提。

用户是材料方向研究者（聚硼硅氧烷/动态键弹性体），**不懂编程**。
技术决策你自己拿主意，跟他汇报用通俗表述。

## 职责

PDF → 结构化文本 + 图坐标（调 MineRU 云服务）。

## 对外接口

| 函数 | 用途 |
|---|---|
| `parse_pdf(path, out_dir)` | 解析，产出 `full.md` + `layout.json` |
| `is_parsed(out_dir)` | 是否已解析过（靠 `layout.json` 判断） |
| `parse_pdf_text(path, out_dir)` | **快速文本层**：PyMuPDF 本地抽字，几秒出 `full.md`，打 `.tier_text` 标记；已有 full.md 不覆盖 |
| `parse_document_text(path, out_dir)` | 快速层分派：pdf → 上一个，docx → `parse_docx` |
| `tier(out_dir)` | `structured`（MineRU / docx）/ `text`（只有快速层）/ `none` |

**两层（2026-10-04）**：MineRU 是云端排队，忙时一篇 pending 半小时。取全文拿到 PDF 先出快速层
（马上能按节读），MineRU 在后台补；成功会覆盖 full.md 并清掉 `.tier_text`。
判断「还要不要跑 MineRU」用 `tier() != 'structured'`，**别再用「full.md 在不在」**。

## 注意

- 解析结果**在精读线和抽取线之间共享**，不重复解析（省钱省时间）。
  改产物结构会同时影响两条线。
- 需要 `MINERU_TOKEN`（走 `config`）。
- 自测刻意**不真的调 MineRU**（省额度），只验接口契约。这是有意的取舍。

## 谁在用它

精读线（`tools/deepread` 的 `_ensure_parsed` 与 `si.read_si`）、抽取线（`tools.extract.batch.ensure_fullmd`）。

改这里的对外接口 = 可能弄坏上面所有调用者。**改签名前先想清楚兼容性。**

## 改完必须做

```
python selftest.py                       # 本块自测，必须全过
python ../../host/doctor/health_check.py     # 全局体检，确认没碰坏别人
```
自测不过就是没改完。**没有自测覆盖的新功能，等于没写。**
