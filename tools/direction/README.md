# tools/direction · 方向地图

**一句话**：一条窄带里，谁做了什么、用了什么方法、实现了什么性能、聚成哪些簇、空白在哪。

## 怎么用（--band 必填，一条窄带一个库）

```
python -m tools.direction bands                      # 现有窄带
python -m tools.direction seeds   --band impact      # 三路取种子（联网）
python -m tools.direction build   --band impact      # 建图（联网，十几分钟）
python -m tools.direction cluster --band impact      # 聚类（纯本地，可反复调）
python -m tools.direction report  --band impact --out 地图.txt
python -m tools.direction stats   --band impact
```

第一次用一条新窄带：先写 `band.json`（见 CLAUDE.md）→ seeds → build → cluster → report。
**之后 cluster / report 都不再联网**，可以反复调参数。

想直接要 idea：

```
python -m tools.direction.brainstorm      # 检索本地库 + 大模型找空白（花钱）
```

## 三路种子

| 来源 | 说明 |
|---|---|
| OpenAlex | 按 `band.json` 的检索式取（**主流程唯一的种子来源**）|
| 窄带引文 | 按学科限制展开 |
| 用户 Zotero | 只在主力机上取得到 |
| 公众号 md | 可选，`wechat` 动作 |

## 方向层：摘要 → 「策略 → 性能 → 应用」（2026-09-07 加，**要花钱**）

```
python -m tools.direction quads --band impact --list        # 还剩多少没抽，不花钱
python -m tools.direction quads --band impact --limit 50    # 先跑 50 篇算单价
python -m tools.direction quads --band impact               # 这条窄带全跑
```

一篇摘要一次小模型调用（默认 `qwen3.8-flash`，控制面板里可换）。
产物是 `data/serving/abstracts/<Wxxx>.json`，**格式与全文抽取完全一样**，
所以 `tools/paperdb` 直接收进同一个三层库，档次标 `摘要`。

**为什么摘要就够用**：付费墙论文 100% 有摘要（2026-08-29 实测 200 篇），
开放获取偏倚咬的是全文不是元数据 —— 方向层因此能覆盖整个领域。
代价是配方、投料量、出处这些天然缺，那是细节层的活。

**抽过的不重抽**（看盘上有没有产物），断了随时接着跑。

## 花钱吗

建图走 OpenAlex，**免费但很慢**（十几分钟）；`brainstorm` 要大模型，花钱。
