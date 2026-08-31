# tools/askworld · 问全世界

**一句话**：向全球文献问一个科学问题，用**取回的原文片段**作答，每条结论带出处。

## 怎么用

```
python -m tools.askworld "聚硼硅氧烷的剪切硬化机理是什么"
python -m tools.askworld "B-N配位键如何提升自修复效率" --since 2020 --top 10
```

只要一份检索列表（不作答、更快）：

```
python -m tools.askworld.search "polyborosiloxane" 20 --since 2021 --impact
```

## 输出

- 一段中文回答
- 一份证据清单：标题 / 年份 / 期刊 / 被引数 / 页码 / 相关度 —— 可直接引用

低相关度的片段会被过滤掉。全被滤光时会明说「没检索到足够相关的证据」，
而不是硬编一个答案。

## 前提与花费

需要 `SCIVERSE_KEY`（在控制面板里填）。检索 + 作答都要花钱。
没有密钥时会提示你改用不要密钥的 `python -m tools.discover "关键词" --openalex`。
