# scopus · Scopus 检索与被引列表

> 你可能是被单独选中这个模块文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这是什么

**一个原子模块**：在 Scopus 检索一次 / 翻一页 / 打开「谁引用了第 n 篇」，读结果列表（EID、标题、作者、刊、年、被引数、类型）。
接管「取全文用的浏览器」里 Scopus 的标签，人登录过。

## 条款与用户的决定（2026-10-09）

Elsevier 网站条款：禁把内容与 AI 工具结合；禁自动程序持续抓取。用户知情后决定按人的频率少量用。
所以：**一次一页、只读**，不导出、不点进摘要页、不批量翻页；频率由 `host/mcp/science.py` 管。
（官方 API 要 Elsevier 开发者 key，用户没申请；以后有 key 应改走 API，对外函数不变。）

## 对外接口

| 函数 | 说明 |
|---|---|
| `search(query, sort='relevance')` | 检索 → 第 1 页；普通词按 TITLE-ABS-KEY，带字段代码就原样 |
| `citing(n)` | 当前结果页第 n 条的被引列表第 1 页 |
| `page(n)` | 当前列表第 n 页 |
| `status()` | 标签 / 登录页 / 验证页 |
| `build_query` / `results_url` / `parse_rows` / `parse_count` / `is_login` / `is_captcha` | 纯函数（自测覆盖）|

## 页面（实测）

`/results/results.uri?src=s&sot=b&sdt=b&sort=<r-f|cp-f|plf-f>&s=<检索式>`；行 `tr` 含 `label[for="document-2-s2.0-…"]`、`h3 a`、
`[data-testid=author-list] button`、`[data-component=document-source]`、`[data-testid=document-publication-year]`，
被引数是指向 `results.uri?s=ref(…)` 的链接；上一行 `tr` 是类型与开放获取。总数「183 篇文献」/「183 documents found」。

## 自测

`python shared/adapters/scopus/selftest.py`（离线）；主力机上加 `--live`。
