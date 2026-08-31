# direction —— 方向地图 / 选题

## 什么时候用我

- 用户说「这个方向有什么规律/空白」「谁在做这块」「帮我想想研究方向」
- 需要看清一条窄带的**版图**：主流分几支、各支的代表作、哪块没人做

## 怎么用

我是 **prompt**（建图慢、brainstorm 花钱）：

```
python -m tools.direction bands                  # 先看有哪些窄带
python -m tools.direction report --band <窄带>   # 纯本地、免费，随便跑
python -m tools.direction seeds|build --band X   # 联网，十几分钟，先跟用户说清楚
```

**已经建好图的窄带，report / cluster / stats 都免费且不联网** —— 优先走这条。

## 什么时候**别**用我

- **只是要一份该读的清单** → `discover`（快得多）
- **窄带还没建库** → 别默默去 build（十几分钟联网）。先 `bands` 看有什么，
  没有就问用户要不要建
- **想找具体某个数值/材料体系** → `paperdb`
- **横向对比找空白格**：先读资源 `paper://compare.md`，很多时候够用了，
  不必建整张引文图

## 边界

- 一条窄带一个库，`--band` 不给就不知道你要哪条
- 聚类结果跟分辨率参数有关；`cluster` 免费可反复调，多试几个再下结论
- 「空白」是这张图里没有，不等于全世界没有 —— 下结论前用 `askworld` 复核一下
