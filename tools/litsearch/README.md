# litsearch · 找文献的原料通道

给自己边找边判断的人（或 agent）用的原料通道。**只读、不动你的 Zotero、不调大模型。**

## 它和「找文献」那个工具的区别

| | `litsearch`（这个） | `discover` |
|---|---|---|
| 给你什么 | **原料**：命中数、摘要、引用关系 | **结论**：一份排好序的清单 |
| 谁做判断 | 你（或 agent）读摘要自己判断 | 机器按「跟你多相关」排好 |
| 拆检索式 | 不拆，你自己写 | 自动拆成 5 个互补检索式 |
| 排序 | 不排 | 相关度 0.6 + 被引 0.25 + 新鲜度 0.15 |
| 花钱吗 | **不花** | 花（拆检索式要大模型）|
| 写 Zotero 吗 | **不写** | 收取那一步会写 |

**什么时候用哪个**：想让机器替你挑 → `discover`；想自己边找边想 → 这个。

## 用法

```bash
# 精确检索：词必须真的出现在标题或摘要里
python -m tools.litsearch "borosiloxane"

# 词组加引号，多词用 AND
python -m tools.litsearch '"phenylboronic acid" AND siloxane'

# 限年份、要更多条
python -m tools.litsearch "borosiloxane" --since 2015 --limit 60

# 取一篇的完整摘要（判断贴不贴题靠它）
python -m tools.litsearch --abstract 10.1021/ma500632f

# 顺着引用网络摸
python -m tools.litsearch --cited-by 10.1021/cm980353l     # 后来谁做了
python -m tools.litsearch --references 10.1021/cm980353l   # 这方向的根在哪
```

每条结果都标着 **【库里有】** —— 你是不是早就有这篇了；**【无摘要】** —— 源头没摘要（Elsevier 常见），只能凭标题判。

## 按意思找（2026-09-26 加）

精确检索要求词真的出现，**换了说法的同一件事搜不到**。按意思找补这个盲区：

```bash
# 一段话描述要找什么（英文），找新的一定要给年份（它不按年份排）
python -m tools.litsearch --semantic "polymer gel that stiffens under impact because dynamic bonds cannot relax" --since 2023

# 照着已经确认相关的几篇找相似的
python -m tools.litsearch --like 10.1039/d3sc00011g,10.1039/d4mh00002a --since 2024 --slice

# 一次对几篇做雪球，按「连到几个种子」排；--newest 优先看新的跟进
python -m tools.litsearch --snowball 10.1039/d3sc00011g,10.1039/d4mh00002a --since 2023 --newest
```

每次最多 50 条（`--slice` 按年切开各取 50）；每次 0.001 美元，免费额度一天约 1000 次。

## 多轮全面检索的台账

agent 替你找一个方向时，会建一本「检索台账」：搜过什么、每篇是哪条路找到的、判没判相关、
每轮新增了几篇相关的。**一轮下来三条路（字面 / 意思 / 引用）都没有新的相关文章，就说明搜得差不多了**。
它还会从已判相关的文章里统计出「别人用的新说法」，下一轮拿去搜。

```bash
python -m tools.litsearch --status 台账名     # 看台账
python -m tools.litsearch --terms 台账名      # 挖出的新说法
```

## 输出里最有用的那个数字

检索会先告诉你 **全世界命中多少篇**：

```
检索词「borosiloxane」：全世界命中 112 篇，返回前 25 篇
```

- 几千篇 → 词太宽，加限定词
- 几十到一两百 → 正好，可以把它捞干净
- 0 篇 → 词写错了，或者**这个组合真的没人做过**（那本身就是个结论）

## 数据来源

OpenAlex（按量计费，免费 key 每天 1 美元额度，日常用不完）。**Elsevier 的文章大多没有摘要**（源头不交），
取摘要时会依次退到证据库原文、Semantic Scholar，都没有就明说。

## 它不干什么

不下载 PDF（那是 `getpdf`）· 不写 Zotero（那是 `getpdf --to-zotero`）·
不给全文（先 `paper_fulltext` 拿 id，再 `library_outline` 看菜单、`library_section` 取节）·
不猜贴题度排序（要机器替你排就用 `discover`；按意思找的相似度、雪球的「连到几个种子」是可数的事实，不算猜）。
