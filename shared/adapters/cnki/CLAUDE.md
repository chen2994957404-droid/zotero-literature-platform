# cnki · 中国知网（学位论文 / 期刊 / 会议 / 中国专利）

> 你可能是被单独选中这个模块文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这是什么

**一个原子模块**：在知网检索一次 / 翻一页 / 读一篇的摘要页，把页面文字解析成字段读回来。

和 `chemdb`、`polyinfo` 一样**不自己发请求**，接管主力机「取全文用的浏览器」（CDP 调试口，地址同
`pdf_fetch.cdp_url()`）里知网的标签。学校按出口 IP 授权，不用登录。

## 为什么是这个形状（2026-10-09 实测）

- 结果页网址不随检索变（前端渲染）：翻页只能在页面上点，所以**摘要页在新标签里开、读完就关**，结果页不动。
- 腾讯拼图验证码 `#tcaptcha_transform_dy` **平时也挂在页面里**，只是移到屏幕外（top=-1000000、透明度 0）。
  判断弹没弹看位置与透明度（`captcha_active`），只看元素在不在会一直误报。
- 「博士 / 硕士」标签藏在「学位论文」的下拉里，Playwright 的 click 会说看不见 —— 用页面里的 `a.click()`。

## 职责与边界

- 只读：检索、翻页、摘要页。**不下载全文**：知网对批量下载封整个学校的出口 IP；要全文请人点「PDF下载」。
- 撞拼图 → 立刻回 `CAPTCHA_REQUIRED`，页面原样留着（摘要页的新标签也不关）；人拖完后 `current()` 读最新的知网标签。
  **这块里没有、也不许加任何拖拼图的代码。**
- 频率（间隔、每天上限、缓存）归调用方（`host/mcp/science.py`）。

## 对外接口

| 函数 | 说明 |
|---|---|
| `search(query, kind='all', sort=None)` | 检索（按「主题」）→ 第 1 页；kind：all / journal / thesis / phd / master / conference / patent |
| `page(n)` | 结果页上停着的那次检索的第 n 页 |
| `detail(n=0, url='')` | 摘要页：摘要、关键词、DOI、导师、学科专业、学位论文目录、专利主权项…… |
| `row_url(n)` | 结果页第 n 条的摘要页链接（不导航）|
| `current()` / `status()` | 不导航：读最新知网标签 / 看验证码挡没挡着 |
| `parse_rows` / `parse_detail` / `parse_counts` / `parse_total` / `captcha_active` / `kind_selector` | 纯函数（自测覆盖）|

## 页面长什么样（改版只改 `KINDS` 和几段 JS）

| | 元素 |
|---|---|
| 首页检索框 / 按钮 | `#txt_search` / `input.search-btn` |
| 结果总数 | 正文「共找到 498 条结果 1/25」|
| 切库 | `a[name=classify]`：`resource=JOURNAL / DISSERTATION / CONFERENCE`，博士 `data-chs=CDFD`、硕士 `CMFD`、中国专利 `SCPD`；`span` 是名字、`em` 是条数 |
| 结果行 | `table.result-table-list tbody tr`，`td` 的 class：seq / name / author / source / date / data / quote / download；专利是 seq / name / inventor / applicant / data / date（申请）/ date（公开）|
| 收藏按钮 | `a.icon-collect[data-dbname][data-filename]`（库名 + 文件名，专利是专利号）|
| 排序 | `#orderList li`（文字：相关度 / 发表时间 / 被引 / 下载；专利：相关度 / 公开日 / 申请日）|

## 自测

`python shared/adapters/cnki/selftest.py` —— 纯离线。真查一次：主力机上加 `--live`。
