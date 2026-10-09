# jcr · Journal Citation Reports（Clarivate）

> 你可能是被单独选中这个模块文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这是什么

**一个原子模块**：查一本刊（刊名 / 缩写 / ISSN）在 JCR 的期刊页，读回 JIF、不含自引的 JIF、JCI、开放获取比例、
每个学科的排名 / 分区 / 百分位。接管「取全文用的浏览器」里 JCR 的标签，人登录过 Clarivate 账号。

## 条款与用户的决定（2026-10-09）

Clarivate Terms v3.3：禁抓取；未签 AI 附加协议不得把其数据用于 AI 系统；禁文本数据挖掘。用户知情后决定一次一本地查。
所以：**只查单本刊**，不导出、不翻学科全表；结果**不写进** `journals.json`（期刊分级仍只用 OpenAlex 开放数据）。

## 对外接口

| 函数 | 说明 |
|---|---|
| `journal(q, year=None)` | 刊名 / 缩写 / ISSN → 期刊页字段（没同名时取下拉第一个并写进 warnings）|
| `status()` | 标签在不在、是不是登录页 |
| `parse_profile` / `pick_suggestion` / `is_login` | 纯函数（自测覆盖）|

## 页面（实测）

首页 `#search-bar` → 下拉 `li.suggestion-item p.journal-title` → `/jcr-jp/journal-profile?journal=<刊名>&year=<年>`。
「Rank by Journal Impact Factor」下 `CATEGORY / 名字 / 19/96 / JCR YEAR	JIF RANK	JIF QUARTILE	JIF PERCENTILE / 2025	19/96	Q1	 / 80.7`；
「Rank by JIF before 2023」之后是旧的分版排名，不取。登录失效跳 access.clarivate.com/login。

## 自测

`python shared/adapters/jcr/selftest.py`（离线）；主力机上加 `--live`。
