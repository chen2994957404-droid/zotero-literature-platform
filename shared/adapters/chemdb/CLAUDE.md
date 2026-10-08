# chemdb · SciFinder / Reaxys 检索

> 你可能是被单独选中这个模块文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这是什么

**一个原子模块**：在 SciFinder 或 Reaxys 里搜一次（或翻一页），把结果列表那一页的**文字**读回来。

和 `pdf_fetch` 一样**不自己发请求**，接管主力机上那个「取全文用的浏览器」（CDP 调试口，
地址同 `pdf_fetch.cdp_url()`）。两个库都要人在那个浏览器里**登录过一次**
（SciFinder 是个人 CAS 账号；Reaxys 是机构登录），登录永远是人做。

## 为什么不用它们的官方接口（2026-10-08 查证）

- **SciFinder**：官方接口是给电子实验记录本这类合作软件的，搜索只回一个「去网页看」的链接，
  登录只支持人在浏览器前（PKCE），手册明说服务器对服务器不适用。
- **Reaxys**：2026-02 起有真数据接口（OData，client_credentials），但要单位另订接口，
  网页订阅不含。学校订了的话，应当改走那条（新写一个实现，对外函数不变）。

## 职责与边界

- 只读：搜索、翻页、读文字。**不导出、不批量点详情、不登录、不截图**（后台标签不渲染画面）。
- **频率不归这块管**：每次间隔、每天上限由调用方（`host/mcp/science.py`）管。
  CAS 学术条款禁止「用脚本自动化本该手工的操作」，Elsevier 页脚写明保留文本挖掘与 AI 训练权利 ——
  用户 2026-10-08 知情后决定按人的频率小量用，所以上限要低、要在服务端。
- 自己连浏览器，不借 `pdf_fetch._connect`：那个连上时会清扫多余标签，可能关掉取全文作业正开着的页。

## 对外接口

| 函数 | 说明 |
|---|---|
| `search(db, query, kind='references', max_chars=30000)` | 搜一次，读结果列表第 1 页 |
| `page(db, n, max_chars=30000)` | 这个库标签上停着的结果列表的第 n 页 |
| `page_url` / `page_no` / `is_login` / `clean_text` / `count_of` | 纯函数（自测覆盖） |

返回 dict 的 `code`：`OK` / `LOGIN_REQUIRED` / `NO_RESULTS` / `NO_SEARCH` / `NAVIGATE_FAILED` / `TIMEOUT`。
浏览器连不上、没装 playwright 才抛异常（沿用 `pdf_fetch.BrowserUnavailable` / `PlaywrightMissing`）。

## 页面长什么样（实测，改版只改 `SITE`）

| | SciFinder | Reaxys |
|---|---|---|
| 搜索框 | `#search-text-input` + `#submit-search-button` | `#id-quick-search-input` + 回车 |
| 搜完先到 | 总览 `/search/all/<id>`，每类一个 `View All …` | 预览：整句拆成几组子查询，各带数目和 `View Results`（`.e2e-view-results`），从严到宽排 |
| 列表页 | `/search/reference/<id>/<页码>` | `…/list/<uuid>/<页码>/desc/WEIGHT` |
| 结果数 | 正文 `26 Results` | 标题 `134 Documents for …` |
| 列表里有 | 标题、作者、刊、年、摘要片段、左侧筛选项计数、CAS Newton 的 AI 摘要 | 标题、作者、刊、年、**DOI**、被引数、命中片段、AI 摘要、筛选项名 |

⚠ 浏览器开了网页翻译时，读到的是**译文**（Edge 直接改写页面文字）。2026-10-08 用户已对 Reaxys 关掉。

## 自测

`python shared/adapters/chemdb/selftest.py` —— 纯离线。真搜一次：主力机上加 `--live`。
