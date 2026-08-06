# 找新文献 · 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这个文件夹是什么

帮用户往文献库里**补新文献**：按主题去外部检索、标出哪些库里已有、
按 DOI 导入 Zotero，以及基于已有积累做研究构想。

用户是材料方向研究者（聚硼硅氧烷/动态键弹性体），**不懂编程**。

## 各文件职责

| 文件 | 干什么 |
|---|---|
| `find_papers.py` | 按关键词检索外部文献库，对照本地库标记「已有/新的」 |
| `import_by_doi.py` | 按 DOI 把文献加进 Zotero |
| `zotero_add_thesis.py` | 添加学位论文类条目 |
| `brainstorm.py` | 基于横向对比表做研究构想（找机理×性能的空白格） |

## 依赖

- **积木**（`../modules/`）：`paper_discovery`（真正的检索能力在这）、`zotero_client`、
  `llm_client`、`config`
- 数据：`workflow_data/structured/compare.md`（brainstorm 的输入）

**核心检索逻辑在积木 `modules/paper_discovery` 里，要改它请让用户改选那个文件夹。**
本文件夹里的脚本只是它的调用者和命令行外壳。

## 注意事项

1. **写 Zotero 库是有副作用的操作**（导入文献会改用户的库），动手前先跟用户确认。
2. 检索结果要标出「库里已有」，否则用户会重复导入 —— 之前清理重复文献花了不少功夫
   （库从 191 篇去重到 165 篇）。
3. brainstorm 用 `deepseek-v4-pro`（需要推理质量）。

## 改完怎么验证

```
python find_papers.py "polyborosiloxane" 8
```
应返回结果列表，并正确标出哪些库里已有。
