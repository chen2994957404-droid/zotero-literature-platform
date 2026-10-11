# tansoole · 探索平台（泰坦科技）药品搜索

> 你可能是被单独选中这个模块文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这是什么

**一个原子模块**：在探索平台（tansoole.com，用户平时买药品的地方）搜一次（或翻一页），
把结果列表里的**明文栏**读回来：品牌、货号、规格、纯度、等级、货期（现货 / 几个工作日 / 期货）、能直接买还是要询价。

和 `chemdb` / `polyinfo` 一样**不自己发请求**，接管主力机上那个「取全文用的浏览器」（CDP 调试口，
地址同 `pdf_fetch.cdp_url()`）里探索平台的标签。人在里面登录过一次（2026-10-11 用户登录）。

## 为什么是这个形状（2026-10-11 查证）

- 没有公开的程序接口；交易条款（`/help/jytk.html`）、注册页里没找到禁止程序访问的原文。
- **价格两栏是特制字体打乱的**：页面文字是 `ɎŁŵŁŁ` 这类乱码，人眼看是数字 —— 网站专门防程序抄价格。
  每行「复制」按钮的 onclick 里有明文价格，那是同一道防护的漏洞。
- 用户知情后定：**价格一律不读**（不读 `li.row05`、不解字体、不读复制按钮）。价格走 SciFinder 供应商页（`chemdb` kind=suppliers）。
  **这块里没有、也不许加任何读价格的代码**（自测里有一条专门查抽取脚本没碰这几处）。

## 职责与边界

- 只读：搜索、翻页、读列表。不加购物车、不询价、不下单、不登录。
- 频率不归这块管：间隔、每天上限、缓存由调用方（`host/mcp/science.py`）管。

## 对外接口

| 函数 | 说明 |
|---|---|
| `search(query)` | 搜一次（CAS 号 / 中英文名 / 货号）→ 第 1 页（每页调到 100 条） |
| `page(n)` | 当前搜索的第 n 页 |
| `status()` | 标签在不在、登没登录 —— 只看浏览器 |
| `parse_spec` / `parse_lead` / `norm_row` / `summarize` / `parse_count` | 纯函数（自测覆盖） |

返回 dict 的 `code`：`OK` / `NO_RESULTS` / `NO_SEARCH` / `CAPTCHA_REQUIRED` / `NAVIGATE_FAILED` / `TIMEOUT`。

## 页面长什么样（实测，改版只改这里）

| | |
|---|---|
| 搜索 | `/search/search.htm?gloabSearchVo.queryString=<词>`（等同在首页 `#demandName1` 里搜） |
| 化合物信息 | `.list-reagent-info`：`li.name` 中文名、下一个 `li` 英文名、`li.mes` 里 CAS 号 / MDL 号 / 分子式 / 分子量 |
| 一行商品 | `ul.show-list.show-list-con`（表头是 `.show-list-head`），列按 `li` 顺序：`row04` 产品编号（带详情链接）· `row10` 原货号 · `row10` 品牌 · `attrrow15` 规格 · `parameterrow15` 纯度 · `row04` 等级 · `row05`×2 价格（**不读**）· `row07` 特价标记 · `row06` 货期 · `row10` 查库存按钮 · `row03` 购买 / 询价 |
| 翻页 | layui：`.layui-laypage-count`「共 55 条」· `.layui-laypage-limits select`（50 / 100 / 300）· `.layui-laypage-skip` 输入页码 + 按钮 |
| 别的品类 | `.pro-show-search-other-list`「继续搜索其它品类: 抑制剂・激动剂2条, …」 |
| 登录 | 页头有「退出登录」= 已登录 |

## 自测

`python shared/adapters/tansoole/selftest.py` —— 纯离线。真搜一次：主力机上加 `--live`。
