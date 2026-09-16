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

## 盯哪些刊，分三档

`data/serving/journal_watch.json`：每条 `name` + `issn` + `tier`。第一次跑会用种子清单（59 本，按证据库里 987 篇的
真实出处拟的，ISSN 都在 Crossref 上逐个验过）把文件建出来，之后你自己改。不想盯的加 `"off": true`，不用删。

| 档 | 回答什么 | 谁 | 自动升 1 级 |
|---|---|---|---|
| A 方向层 | 行业往哪走、新概念第一次出现 | Nature/Science 系、JACS、Angew、AM、AFM、Chem Rev… | OpenAlex 分类是软物质/高分子/材料力学的 |
| B 领域层 | 这个体系怎么做、参数在哪 | Macromolecules、Polym Chem、Chem Mater、Polymer、Soft Matter… | 同上（几乎都过） |
| C 宽口层 | 两头都有、噪音最大 | CEJ、AMI、Small、Adv Sci、JMCA、Green Chem… | 不自动，你点名才取 |

**门槛不看你的库**（2026-09-16 用户定：默认状态下他的库和一切断开）。用的是 OpenAlex 的学科分类 —— 普适信号；
它比 Crossref 晚几天到两周收录，所以刚登记的文章先在雷达里等分类到了再过闸。
「引了证据库里几篇」仍然记录，只在 `--跟我相关` 时用来排序。

## 雷达库（0 级）

每篇的题目 / 摘要 / 作者 / 参考文献 DOI 都存进 `data/serving/radar.db`（一篇 4 KB）。
监听服务每天自动巡逻一次；`python -m tools.journalwatch --回填 3` 把过去三年也拉进来（一晚上，断了再跑接着来）；
`--雷达` 看现在有多少。它是**雷达**不是证据库：知道外面出了什么、引了我库里哪几篇，供相关度筛选用。
摘要看出版社：Wiley / ACS 基本都有，Elsevier 一律没有（他们不给登记处）。

## 它怎么知道「新」

直接问 Crossref 的 DOI 登记处：出版社注册 DOI 的那一刻就有了，比期刊邮件、比 OpenAlex 都早。
不要账号、不要密钥、不花钱。见过的 DOI 记在 `data/state/journal_watch_seen.json`，
删了只会把最近几天的再当成「新」列一遍。

## 每天自动做什么（监听服务里，2026-09-16 起）

1. 巡逻：59 本刊最近 3 天新登记的 → 进雷达
2. 补摘要：OpenAlex 补 Crossref 没给的（每天最多 200 批）
3. **补分类**：OpenAlex 的 topics（普适门槛的原料）
4. **过线 → 升 1 级**：A/B 档且分类是软物质/高分子的入队，每天最多取 10 篇（A 档先、新的先），
   正本 + SI 落地，落地流水线随后自动解析。取不到的隔天再试，最多四天。
   队列在 `journal_watch_seen.json` 的 `queue` / `harvested`。

不精读（那要花模型钱，仍只由你打标签触发）、不写 Zotero。
