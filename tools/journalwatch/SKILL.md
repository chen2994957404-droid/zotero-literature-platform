# journalwatch —— 盯新刊

## 什么时候用我

- 用户问「这周好刊有什么新文章」「Macromolecules 最近出了什么」
- 想知道「我盯着的那些期刊有没有新的、库里还没有的」
- 定时巡逻（每天一次列首见的）

## 怎么用

我是 **tool**（免费、只读、不写 Zotero、不取全文）：

```
python -m tools.journalwatch [--天 7] [--只看新的] [--刊 Macro] [--含摘要]
python -m tools.journalwatch --雷达           # 雷达库有多少
python -m tools.journalwatch --回填 3         # 三年回填（一晚上，人点）
```

盯哪些刊在 `data/serving/journal_watch.json`（name + ISSN，用户自己改；不想盯的加 `"off": true`）。
列出来的编号可以直接 `python -m tools.discover.collect 1,3,5-7` 收进库。

## 什么时候**别**用我

- **按关键词找文献** → `discover` / `lit_search`（我只按刊列，不按题目搜）
- **默认不看用户的库**（他定的）：列表、过线都只按刊物档位 + OpenAlex 学科分类；只有他明说「跟我相关的」才加 `--跟我相关`
- **要取全文** → 挑好编号后走 `collect` / `getpdf`；我不会自动下载
- **查某一篇的元数据** → `crossref.work(doi)` 或 `library`

## 边界

- 用的是 Crossref 的 **DOI 登记日**，比出版日早；刚登记的全文往往过几天才挂出来
- 一本刊一次最多列 1000 条，窗口最长 60 天
- Nature / Science 的新闻、社论已经滤掉（只留 journal-article）
