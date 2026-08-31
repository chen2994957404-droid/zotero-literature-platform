# tools/discover · 找新文献

**一句话**：从全世界找该读的文献 → 对照我的库 → 按「跟我多相关」排序 → 挑几篇收进 Zotero。

## 怎么用

```
python -m tools.discover "polyborosiloxane dynamic bond"
python -m tools.discover "我的材料回弹太差怎么解决" --解决问题
python -m tools.discover "shear stiffening gel" 30 --since 2020
python -m tools.discover "..." --openalex     # 改用免费的 OpenAlex（不用密钥）
```

看完想收哪几篇（**这一步会写 Zotero**）：

```
python -m tools.discover.collect 1,3,5-7
```

入库后在 Zotero 打「待处理」标签即自动精读。

## 两种模式

| 模式 | 求什么 | 怎么拆检索式 |
|---|---|---|
| 默认（系统调研）| **全** | 术语变体、同义词、上位/下位概念 |
| `--解决问题` | **准** | 机理、方法、性能指标、应用场景等不同角度 |

## 它做了什么（为什么比直接搜好）

1. 一句话需求 → 拆成多条英文检索式（大模型）
2. 多式并检 → 合并去重
3. **引文雪球**：挑几篇种子，把它们的参考文献与施引文献一并捞进来
4. 对照本地库标出「已在库」
5. 按「跟他多相关 + 影响力 + 新鲜度」排序

雪球本体在 `shared/adapters/snowball/`（纯 API 包装），这里只做编排。

## 花钱吗

拆检索式要大模型；Sciverse 那条路要密钥。`--openalex` 改用免费源。
