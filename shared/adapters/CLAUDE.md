# adapters · 外接口环 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。

## 判据：什么东西该放这里

**「外部世界变了就得改它」的代码。** 每一块包住**一个**外部系统或持久化存储。

这一环就是宪法【首要判据】说的那层皮：
> 「稳定的自己做（接口），发展中的用现成（实现）。」

外层是我们自己定义的函数名，多年不变；内层是随时可以整块换掉的第三方。
`llm_client` 是范例：外层 `chat` / `chat_json` 从没变过，
内层实现已经换过 DeepSeek → Ollama → 硅基流动三家，上层代码一行没动。

## 一条特权，也是一条重责

**只有这一环允许联网、允许 import 第三方 SDK。**

这不是风格偏好 —— 它是「换掉 MineRU 只需改一个文件」这个承诺的**全部保证**。
如果 `tools/` 或 `host/` 也能直接发 HTTP 请求，那个承诺当场作废：
换服务时你得满仓库找 `urlopen`。守卫会强制这条（`python -m pytest`）。

## 现有成员

| 块 | 包住谁 |
|---|---|
| `zotero_client` | Zotero。读：本地 API、找正文 PDF、判断有没有 SI；**写：改标签、传附件（`_web.py`，全项目唯一碰 api.zotero.org 的文件）** |
| `llm_client` | 各家大模型（云端 / 本地 Ollama）|
| `embed` | 本地 bge-m3 向量化 |
| `pdf_parse` | MineRU 云端 PDF 解析 |
| `openalex` | OpenAlex 学术检索（免费无密钥）|
| `sciverse` | Sciverse 学术检索（4.55 亿条，需密钥）|
| `snowball` | 引文网络雪球扩展（建在 openalex 之上）|
| `vectordb` | 向量库（当前实现 Chroma）|

## 写一块新 adapter 的规矩

1. 对外只暴露**我们自己命名**的函数，不要把第三方的概念漏出去
   （例：`vectordb.query()` 返回拆平的结果，而不是 Chroma 那套「每字段套一层 list」）
2. 失败要抛 `core.errors` 里的分类异常，让调用方知道**该不该重试**：
   限流 → `RateLimited`、服务没开 → `ServiceUnavailable`、密钥不对 → `AuthError`
3. 依赖只能向下（`core`），不许 import `domain` / `pipelines` / `apps`
4. 必须带 `selftest.py`（宪法铁律 3）

## 反面教材（阶段 2 修掉的）

同一个 OpenAlex API 曾被**三处各实现一遍**（snowball / paper_discovery / find_papers）。
后果不只是重复：三份实现行为不一致（只有一份有退避重试），
而且**字段名各叫各的** —— 一处发 `cited_by`、一处读 `cited`，两边对不上，
于是走 OpenAlex 检索时引用数**永远是 0**，还连累了按被引排序的打分。

**同一个外部系统只能有一个 adapter。** 发现第二份，就是该合并的信号。
