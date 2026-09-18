# glossary · 领域术语表：缩写 → 中文译名

> 你可能是被单独选中这个文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这是什么

**一个原子模块**，住在 `shared/domain/`（纯逻辑层）。

本地小模型精读时数字不编（有回查）但**名字会错**（PVDF 写成聚丙烯腈）。命名是封闭世界，
查表能替代记忆。表从用户认可的公众号范文里挖（「中文名（英文缩写）」写法），
第二层可从 Wikidata 补（联网，住 adapters）。

用户是材料方向研究者（聚硼硅氧烷 / 动态键弹性体），**不懂编程**。

## 谁在用

- `tools/deepread`：每栏提示词末尾塞「这篇里出现过的缩写 → 译名」；生成后 `mismatches` 抓错译重写；
  `python -m tools.deepread --建术语表` 从范文重建表（产物 `data/serving/glossary.json`，可重建）
- `tools/ask`：答案里的错译

## 对外接口

| 函数 | 说明 |
|---|---|
| `mine(texts)` | 中文文本 → {英文: Counter(中文)} |
| `build(counts, min_count=2, keep=3)` | 洗成表：去动词前缀、后缀变体合并、一次性的不要、歧义都留 |
| `lookup(table, term)` | 译名列表 |
| `terms_in(table, text)` / `prompt_block(table, text)` | 原文里出现过的词 / 提示词那一段 |
| `mismatches(table, output)` | [(缩写, 写成了, 应为)] |

## 它不做什么

- 不读盘、不联网：表是 dict，由调用方传进来（deepread 从 `paths.glossary()` 读）。
- 不改产出：只报，重写由调用方带着提示去做。

## 验证

```
python shared/domain/glossary/selftest.py
python -m pytest tools/deepread -q
```
