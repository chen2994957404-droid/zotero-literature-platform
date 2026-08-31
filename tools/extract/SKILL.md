# extract —— 把文献抽成结构化字段

## 什么时候用我

- 用户说「把这批文献的数据抽出来」「做一张对比表」
- 你要给 `paperdb` 补料：想筛的字段在库里还是空的

## 怎么用

我是 **prompt**（每篇都花钱）。讲清代价、用户点头后：

```
python -m tools.extract <KEY> --parse      # 单篇
python -m tools.extract --parse            # 全库增量（更贵，只在主力机）
```

**只是想看对比表就别抽**：直接读资源 `paper://compare.md`（免费、即时）。
另外两张：`paper://compare_PBS.md`、`paper://compare_reviews.md`。

## 什么时候**别**用我

- **只是要查已有的结构化数据** → `paperdb_find` / 读 `paper://compare.md` 资源
- **要给人读的详细报告** → `deepread`（我抽的是字段，不是文章）
- **这篇还没精读过** → 我会先调 MineRU 解析（`--parse`），那也花钱；
  先确认用户确实要这一篇
- **想省钱做粗筛** → `--coarse` / `--local` 走本地模型，零成本，但**只够粗筛**

## 边界

- 精层 vs 粗层差别很大：粗层来自 Zotero 全文索引 + 本地小模型，
  拿它下结论前先看 `paperdb_stats` 的有值率
- 抽取自带回查（漏的补、编的删），所以一篇会调不止一次模型，别按「一篇一次」估成本
- 输出是**英文**，这是刻意的；给用户看时你来翻译
