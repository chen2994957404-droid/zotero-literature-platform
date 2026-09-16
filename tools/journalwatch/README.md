# tools/journalwatch · 盯新刊

**一句话**：你盯着的那些好期刊最近新登记了哪些论文，一张单子列出来，标出库里有没有。

## 怎么用

```
python -m tools.journalwatch                 最近 7 天
python -m tools.journalwatch --天 3 --只看新的
python -m tools.journalwatch --刊 Macro --含摘要
```

看完想收哪几篇（编号就是单子上的编号）：

```
python -m tools.discover.collect 1,3,5-7
```

## 盯哪些刊

`data/serving/journal_watch.json`：每条 `name` + `issn`。第一次跑会用一份种子清单
（28 本材料/化学/综合类刊，ISSN 都在 Crossref 上验过）把文件建出来，之后你自己改。
不想盯的加 `"off": true`，不用删。

## 它怎么知道「新」

直接问 Crossref 的 DOI 登记处：出版社注册 DOI 的那一刻就有了，比期刊邮件、比 OpenAlex 都早。
不要账号、不要密钥、不花钱。见过的 DOI 记在 `data/state/journal_watch_seen.json`，
删了只会把最近几天的再当成「新」列一遍。

## 它不做什么（现在）

- 不筛相关度 —— 列的是这本刊的**全部**新论文，先看几周再定线
- 不自动下载、不写 Zotero —— 收哪篇由你点
