# domain/outline · 一篇论文 → 稳定的骨架 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。

## 这块是什么

**给模型点菜用的菜单。** 全文平均约 5 万字符（约 1.3 万 token），而一个问题真正要看的往往是两三节 ——
所以别把整篇端上去，先给菜单。纯逻辑：不联网、不写盘、不知道文件在哪（路径由调用方给）。

用户是材料方向研究者（聚硼硅氧烷 / 动态键弹性体），**不懂编程**。

| 文件 | 干什么 |
|---|---|
| `__init__.py` | 骨架：`build_outline` / `section_text` / `menu` / `find_section` / `locate` / `is_current` |
| `scan.py` | 用脚本扫正文：`clean_body`（把 MineRU 的 LaTeX 残渣洗成人话）、`scan_numbers`、`scan_tables` |
| `props.py` | 性能名归一（`PROPERTY_ALIASES`）与「性能: 数 单位」拆分（`parse_property`）—— 给 scan 用 |

## 谁在用

`tools/library`（`library_outline` / `library_section`）、`tools/getpdf/fulltext`（取全文后马上出骨架）、
`host/mcp/science.py`（Claude Science 按节读）。

## 接口

    build_outline(md, si_md='')  → {'sections': [...], 'tables': [...], 'figures': [...], 'stats': {...}}
    section_text(md, outline, 's5' | 's5.p3' | 't1' | 'f2')  → 按地址取原文
    menu(outline)  → 给模型看的几百 token 菜单
    find_section(outline, title) / locate(md, outline, quote)  → 解析升级后节号变了，按标题 / 一句原文找回

**按功能类别归类，不按标题字面**：Results 和 Discussion 有时合并、Experimental 还是 Methods 看期刊、
MineRU 偶尔把图注识别成标题 —— 字面对不齐。类别只有九个：
摘要 / 背景 / 合成 / 方法 / 结果 / 讨论 / 结论 / 非正文 / 未分类。**认不出标「未分类」，不猜。**

## 改之前先读的坑

1. **一级标题是论文题目，不是章节** —— 让它当父节会把整篇带偏
2. **层级要看编号不看 `#`** —— `## 3.` 与 `## 3.1.` 在 markdown 里同级，编号才写着真实层级
3. **字数只算自己那一段** —— 含子节的话各节加起来会超过全文（实测 121%）
4. **改了 `clean_body` 要把 `OUTLINE_VERSION` +1** —— 骨架缓存按「洗过的正文」算签名；
   2026-09-24 改过 `clean_body` 没升版本，1034/1090 篇的缓存位置整体错开几个字，取节时开头被截

`背景` 这一类是硬错误的解药：最常见的错是把引言里别人文献的数当成本文性能，类别标出来模型才有机会不犯。

## 怎么验证

```
python shared/domain/outline/selftest.py     # 离线、毫秒级
python -m pytest -q tools/library            # 骨架的回归测试住在它的主要用户那边
```
