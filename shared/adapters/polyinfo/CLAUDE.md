# polyinfo · NIMS 聚合物数据库 PoLyInfo

> 你可能是被单独选中这个模块文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这是什么

**一个原子模块**：在 PoLyInfo 里查一次（检索 / 样品列表 / 一个样品的详情），把那一页的文字解析成字段读回来。

和 `chemdb` 一样**不自己发请求**，接管主力机上那个「取全文用的浏览器」（CDP 调试口，
地址同 `pdf_fetch.cdp_url()`）里 PoLyInfo 的标签。人在里面用 DICE 账号登录过一次（要 MatNavi 使用批准）。

## 为什么是这个形状（2026-10-09 查证）

- **没有公开的程序接口**；MDR 上的 PoLyInfo 论文不附数据；2017 年 NIMS 文件提过付费接口，文档只在所内。
- 条款禁止批量下载与网页抓取（人工、机器都算），有嫌疑就停账号。
- 网站自带人机验证：**样品详情页每次都要输图片里的字符**；查得频繁时检索也会弹。

用户 2026-10-09 定：不是批量抓，是省掉「人查完截图给 Claude Science」这一步；要人点的时候人点。

## 职责与边界

- 只读：检索、样品列表、一个样品的详情。**不翻全库、不导出、不登录、不填验证码**。
- 撞验证码 → 立刻回 `CAPTCHA_REQUIRED`，页面原样留着；人点完后 `current()` 读那一页（不重查）。
  **这块里没有、也不许加任何识别或填写验证码的代码。**
- 频率不归这块管：间隔、每天上限、缓存由调用方（`host/mcp/science.py`）管，而且要比 SciFinder 更保守。

## 对外接口

| 函数 | 说明 |
|---|---|
| `search(name='', pid='', formula=None, prop='', atoms_only=False)` | 检索 → 结果列表第 1 页（每种聚合物所选性质的中位数 / 众数 / 点数）|
| `samples(pid)` | 一种聚合物的样品列表（每个样品的性质值）|
| `sample(pid, n=1)` | 第 n 个样品的详情：组成、聚合条件、分子量、出处 DOI、原文的组成–性质表 |
| `current()` | 不导航，读标签上现在那一页 |
| `status()` | 标签在不在、登录页、验证码 —— 只看浏览器 |
| `parse_list` / `parse_samples` / `parse_sample_info` / `page_kind` / `is_captcha` / `is_login` / `formula_counts` / `check_id` | 纯函数（自测覆盖）|

返回 dict 的 `code`：`OK` / `NO_RESULTS` / `LOGIN_REQUIRED` / `CAPTCHA_REQUIRED` / `NOT_FOUND` / `NAVIGATE_FAILED` / `TIMEOUT`。

## 页面长什么样（实测，改版只改这里）

| 层 | 网址 | 关键元素 |
|---|---|---|
| 检索页 | `/PoLyInfo/search` | 第 1 个文本框 = PID/COID/BDID，第 2 个 = 聚合物名；`select[name=p-cu-atom1]` × 6 = 分子式元素格（后面跟个数框）；`#property1_name_part` = 性质；按钮 `a.pi-body__pi-button` 文字 POLYMER SEARCH |
| 结果列表 | `/PoLyInfo/polymer-list` | 「Matches: N polymers were found.」；每条 `N. 名字` + `PID: … CU formula: … Nsamples` + 性质行（Tab 分隔：中位 / 众数 / 方差 / (N points)）；`a.samples_link[data-pid]` |
| 样品列表 | `/PoLyInfo/sample-list` | 「Number of data points: N」；行 `序号\t样品编号\t材料类型\t添加剂\t类型`，下面「性质名 值[单位]」；`a.sample_list_row_sample_id` |
| 样品详情 | `/PoLyInfo/sample-information` | Information / Component / Composition / Property / Related Information 五段（Tab 分隔的表）|
| 验证码 | 任何一层 | 正文出现「Type the characters see in the picture below.」|
| 登录 | `dicelogin.b2clogin.com/...` | 「Login with DICE account」|

⚠ 网页翻译开着时读到的是译文。用 PoLyInfo 时把 Edge 翻译关掉。

## 自测

`python shared/adapters/polyinfo/selftest.py` —— 纯离线（三种页面的真实文字样例）。真查一次：主力机上加 `--live`。
