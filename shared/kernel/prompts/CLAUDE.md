# prompts · 提示词的唯一读取口

> 你可能是被单独选中这个积木文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这是什么

**一块「公理件」** —— 平台的最小可复用单元。它只做一件不可再分的事：
**按名字和版本读一段提示词文本**。不联网、不调模型、不认识任何外部服务。

用户是材料方向研究者（聚硼硅氧烷/动态键弹性体），**不懂编程**。
技术决策你自己拿主意，跟他汇报用大白话。

## 职责

**提示词是数据，不是代码。** 每段提示词住在 `<拥有者>/prompts/<名>_v<N>.txt`：

```
tools/deepread/prompts/main_v2.txt      → prompts.load('deepread', 'main@v2')
tools/deepread/prompts/si_v1.txt        → prompts.load('deepread', 'si@v1')
shared/adapters/query_expand/prompts/survey_v1.txt
                                        → prompts.load('shared/adapters/query_expand', 'survey@v1')
```

拥有者**带不带斜杠就是区别**：不带 = 工具名（`tools/<名>/`）；带 = 相对仓库根的包路径。

## ⚠ 唯一的铁律：只增不改

**永远不要编辑一个已有的 `*_vN.txt`。** 要改措辞就新建 `v(N+1)`，旧文件留着。

理由不是洁癖：精读、抽取的每条结果都把 `prompt_ver` 写进了状态库，
`jobs.stale('main_summary', prompt_ver=3)` 靠它回答「哪些该重跑」。
就地改文件会让「这篇是用哪一版跑的」这个问题**永远失去答案** ——
而「精读为什么突然变差了」的答案九成在提示词里。

新增版本后，记得同步两处：
1. 调用方的 `PROMPT_VER` 常量（+1）
2. 该工具 `tool.toml` 的 `prompts` 字段（`host/mcp/registry.check()` 会校验自洽）

## 对外接口

| 函数 | 用途 |
|---|---|
| `load(owner, spec)` | 读文本。`spec` = `'main@v2'`（钉死版本，**推荐**）或 `'main'`（最新） |
| `latest(owner, name)` | 最大版本号；没有返回 None |
| `versions(owner, name)` | `[1, 2, 10]`，升序 |
| `listing(owner)` | `['main@v2', 'si@v1']` —— 每个名字只列最新版，给 tool.toml 校验用 |
| `path(owner, name, ver)` | 拼路径，不检查存在性 |
| `MissingPrompt` | 找不到时抛它（继承 `errors.DataError`：重试没用，要人来看） |

## 两个已经踩过的点

1. **版本要按数字比大小**，不是字符串 —— 否则 `v10 < v2`。自测里有这一项。
2. **空提示词不许静默使用**。文件在但内容是空的，模型会自由发挥，
   产出看着像正常输出，实际全是幻觉。`load()` 遇到空文件直接抛错。

缓存按路径做，因为「只增不改」保证了同一路径的内容永远不变。

## 谁在用它

八个用大模型的工具（deepread / extract / ask / askworld / direction / digitize / curate）
和一个共用件（`shared/adapters/query_expand`）。

## 改完必须做

```
python shared/kernel/prompts/selftest.py     # 7 项，全在临时目录里跑
python -m pytest -q
python host/doctor/health_check.py --offline
```
