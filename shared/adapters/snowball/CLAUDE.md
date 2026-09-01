# shared/adapters/snowball · 引文雪球

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。

## 这是什么

**给几篇种子文献，顺着引用关系滚出一批候选。**

- 后向（backward）：这几篇**引了**谁 —— 找的是这条线的地基
- 前向（forward）：谁**引了**这几篇 —— 找的是后来的新进展

数据全部来自 OpenAlex，本块只是把「按种子循环 + 去重 + 限速」这点事包起来。

## 为什么它在 adapters 而不是自己成一个工具（R3 窗判定）

读完代码就清楚了：`_get` / `_abstract` / `_norm` 全是转发
`shared.adapters.openalex`，`_backward` / `_forward` 是直接拼 OpenAlex 查询，
`expand()` 只有「按种子循环 + 去重 + 限速」——**没有算法，也没有跨块编排**。

那它就是一层 API 包装，归 adapters。唯一那点编排（挑种子 → 扩展 → 并进候选池）
留在 `tools/discover.snowball_more()` 里。

> 顺带解释一个看起来矛盾的地方：本块只有 `discover` 一个使用者，
> 按第三节硬规则 1（下沉规则）「只有 1 个用的不许住 shared/」它该搬走。
> 但**硬规则 3「联网只在 shared/adapters/」优先** —— 把它搬进工具就等于
> 让工具联网，那是换一条更硬的规则去违反。所以 adapters 整环免检下沉规则，
> 架构守卫里写着这条例外。

## 对外接口

```python
from shared.adapters import snowball

snowball.expand(seed_dois, direction='both', limit=200)
# → [{doi, title, year, abstract, cited_by_count, ...}]
```

## 改这块之前要知道的

- **OpenAlex 从 2026-02 起按量计费**（踩坑 #77）——「免费无密钥」那条旧认知已经过期。
  雪球一开就是几十上百次请求，别在循环里再套循环。
- **批量取用会被限流，而且是静默的**（踩坑 #76）：不报错，只是少给你 30%。
  少给的那部分看起来就像「本来就没有」，比报错难发现得多。
- **雪球容易被高被引通用文献带偏**（踩坑 #38）：一滚就滚出一堆「XX 综述」
  「XX 进展」。排序时要同时看「跟我的库像不像」和「是不是通用大热门」——
  那段排序逻辑在 `tools/discover`，不在这里。

## 改完必须做

```
python shared/adapters/snowball/selftest.py     # 本块自测（离线，不打 OpenAlex）
python host/doctor/health_check.py --offline    # 全局体检，确认没碰坏别人
```
