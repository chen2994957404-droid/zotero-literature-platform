# tools/litsearch · 对抗式检索的原料通道 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。

## 这块是什么

**把干净的原料递给调用方，判断由调用方做。** 四个动作：精确检索、取摘要、
前向雪球、后向雪球。每条结果都标「用户库里有没有」。

用户是材料方向研究者（聚硼硅氧烷 / 动态键弹性体），**不懂编程**。

## 它存在的理由（2026-09-09 建）

`tools/discover` 假设的流程是「机器排好序 → 人看编号挑 → 人点收取」。
用户实际要的是**对抗式检索**：先想 → 去取 → 读摘要 → 发现缺什么 → 再取。
那个循环不需要「拆检索式」和「排序」——
调用方自己会写检索式（还能按上一轮读到的东西调整），也会读摘要自己判断贴题度。

**「找文献」这块被拆成两条并行的路，不是一条路的两段**：
- 想让机器替你挑 → `discover`（花钱、要向量库、只在主力机好使）
- 想自己边找边想 → 本工具（免费、只读、哪台机器都一样）

## 为什么必须单独成包

`discover` 整包 `costs_money = true`，守卫要求它注册的每个 tool 都带 `confirm`（每次弹窗）。
对抗式检索一轮要调十几次，每次弹窗这个用法就废了。
同样的判例见 `host/mcp/server.py` 里 `fulltext_status` 那条注释：
**「只读的东西不该被工具包的档位连坐」**。

## 文件

| 文件 | 干什么 |
|---|---|
| `__init__.py` | 四个动作的全部逻辑（拼 filter → 调适配器 → 收尾标 in_library）|
| `cli.py` | 命令行（`python -m tools.litsearch "词"`），只解析参数 |
| `mcp.py` | 四个不弹窗的 MCP tool，只做参数转换 |
| `tool.toml` | 整包免费只读 → `expose = "tool"`，这是它不弹窗的依据 |
| `SKILL.md` · `README.md` | 给 agent 的手册（含**什么时候别用我**）· 给人的说明 |
| `selftest.py` | 纯离线自测：年份 filter 拼法、收尾截断、空词不发请求 |

## 三条别顺手改掉的设计

1. **默认精确检索，不是相关性检索。** 用的是 OpenAlex 的
   `title_and_abstract.search`（词必须真的出现），不是 `search`（模糊相关性）。
   2026-09-09 实测：同一个问题，相关性检索前十条全是不相干的高被引大综述；
   精确检索把 `borosiloxane` 112 篇、`Si-O-B` 247 篇干净地捞了出来。
   **对抗式检索要的是可枚举的召回，不是猜出来的排序。**
2. **一定要把「全世界命中多少篇」透出去。** 那个数字是调用方决定「收窄还是放宽」
   的唯一依据。只给前 25 条不给总数，调用方就是瞎的。
3. **不排序。** 排序要向量库和本地模型，算不出来时会静默退化成「按被引量排」
   （踩坑 #149）—— 一份看起来排过、其实跑偏的清单，比不排更坏。

## 依赖

`shared/adapters/openalex`（检索、取摘要）· `shared/adapters/snowball`（前后向）·
`shared/adapters/zotero_client`（库索引）· `shared/domain/libmatch`（判「有没有」）。

**不 import 任何别的 `tools/*`**（硬规则 2）。库索引的 5 分钟缓存在本包里有一份，
`tools/discover` 里也有一份 —— 出现第三个使用者时，就该把「带缓存的库索引」
提到 `shared/adapters/zotero_client` 里去。

## 怎么验证

```
python tools/litsearch/selftest.py                       # 10 条，纯离线
python -m tools.litsearch "borosiloxane" --limit 5       # 一次真检索（免费）
python -m tools.litsearch --abstract 10.1021/ma500632f   # 取摘要
python -m pytest -q                                      # 架构守卫
```
