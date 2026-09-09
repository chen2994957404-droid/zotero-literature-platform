# litsearch · 找文献的原料通道

给自己边找边判断的人（或 agent）用的四个动作。**全部免费、只读、不动你的 Zotero。**

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

每条结果都标着 **【库里有】** —— 你是不是早就有这篇了。

## 输出里最有用的那个数字

检索会先告诉你 **全世界命中多少篇**：

```
检索词「borosiloxane」：全世界命中 112 篇，返回前 25 篇
```

- 几千篇 → 词太宽，加限定词
- 几十到一两百 → 正好，可以把它捞干净
- 0 篇 → 词写错了，或者**这个组合真的没人做过**（那本身就是个结论）

## 数据来源

OpenAlex（免费、不要密钥、不限量）。摘要覆盖不是 100%，个别文献没有摘要是源头就没有。

## 它不干什么

不下载 PDF（那是 `getpdf`）· 不写 Zotero（那是 `getpdf --to-zotero`）·
不给全文（先 `paper_fulltext` 拿 id，再 `library_outline` 看菜单、`library_section` 取节）·
不排序（要机器替你排就用 `discover`）。
