# ccdc · CCDC Access Structures（CSD / ICSD 单个晶体结构查询）

> 你可能是被单独选中这个模块文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这是什么

**一个原子模块**：在 CCDC Access Structures 检索一次（化合物名 / CCDC 号 / 结构代码 / DOI / 作者），读结果列表（最多 30 条），
或点开一条读详情（CCDC 号、空间群、晶胞、数据 DOI、关联论文 DOI）。接管主力机「取全文用的浏览器」里 CCDC 的标签，
人在里面登录过 CCDC 账号。

## 条款与用户的决定（2026-10-09）

条款原文：「Programmatic access to these services is not permitted」，禁系统性检索与下载。
用户知情后决定按人的频率少量用（「跟 SciFinder 一样省去截图……遇到人机验证我都会来点，也只做少量需要的检索」）。
所以：**一次一页、只读、不下载 CIF**；撞验证页回 `CAPTCHA_REQUIRED`，人填，**不许加任何填验证码的代码**；
间隔与每天上限由 `host/mcp/science.py` 强制且要低。

## 对外接口

| 函数 | 说明 |
|---|---|
| `search(compound='', ident='', doi='', author='', database='Published')` | 检索 → 列表（最多 30 条，超过标 truncated）|
| `detail(n)` | 当前列表第 n 条的详情 |
| `current()` / `status()` | 不导航：读当前页 / 看验证页 |
| `search_url` / `parse_results` / `parse_detail` / `is_captcha` | 纯函数（自测覆盖）|

## 页面（实测，改版只改这里）

- 检索网址：`/structures/Search?Compound=…&Ccdcid=…&Doi=…&Author=…&DatabaseToSearch=Published`
- 结果行：`input[type=checkbox][data-refcode][data-depositionnumber]`，行文字含 Space Group / Cell / Compound Name / Synonyms
- 详情：点 `.refcode`，右侧面板「Additional details」下 Tab 分隔的 Deposition Number / Data Citation / Deposited on，
  「Associated publications」下每行一篇（带 DOI）
- 验证页：标题「Validation request」/ 正文「confirm you are not a robot」

## 自测

`python shared/adapters/ccdc/selftest.py`（离线）；主力机上加 `--live` 真查一次。
