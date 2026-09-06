---
name: getpdf
description: 一批 DOI → 正文 PDF 到手，可直接收进 Zotero（借真实浏览器，用机构订阅权限）。什么时候用：用户说「把这几篇下下来」「这批的正文我要」；discover 找出了该读的清单，下一步是把正文弄到手；要精读某篇，但 library 说库里没有 PDF
---

<!-- 本文件由 host/codegen/skills.py 生成，**别手改**。改源：tools/getpdf/SKILL.md + tools/getpdf/tool.toml -->

> **动手之前先看这三行**（取自 `tools/getpdf/tool.toml`）：
> 不花钱 · **有副作用**：向出版商网站发真实请求 —— 量大会触发风控，被封的是整个机构的 IP、写 data/raw/_incoming/getpdf/*.pdf、--to-zotero 时**写用户的 Zotero 库**：建条目、挂 PDF 附件、建合集（不可逆） · **只能在运行端（主力机）跑**
> MCP 暴露方式：`prompt`（**由人在客户端点，模型不能自己发起**）
> 命令行：`python -m tools.getpdf`

# getpdf · 把正文弄到手

**一句话**：给 DOI，借一个真实浏览器把正文 PDF 取到本地。

## 什么时候用我

- 用户说「把这几篇下下来」「这批的正文我要」
- `discover` 找出了该读的清单，下一步是把正文弄到手
- 要精读某篇，但 `library` 说库里没有 PDF

## 什么时候**别**用我

- **用户只是想知道某篇在不在库里** → `library search`，免费秒回
- **那篇是开放获取的** → Zotero 自己的「查找可用 PDF」就够了，不用惊动出版商
- **用户想要「把某个期刊/某个方向的全下下来」** → 别做。那是扫库，
  会触发出版商风控，**封的是整个机构的 IP，全校跟着断**。
  正确做法是先用 `discover` 筛出真正该读的那几十篇，再取这些。
- **人不在那台机器跟前** → 撞上人机验证时没人能点，整批会卡住

## 用法

```bash
python -m tools.getpdf --probe                    # 先确认浏览器在
python -m tools.getpdf 10.1016/j.cej.2025.164092  # 取一篇
python -m tools.getpdf --file dois.txt            # 一批，一行一个
python -m tools.getpdf --file dois.txt --gap 30 --limit 10

# 顺手收进 Zotero（**会写用户的库**）
python -m tools.getpdf --file dois.txt --to-zotero              # 默认「建库」用途
python -m tools.getpdf 10.1016/xxx --to-zotero --purpose 精读    # 标成重点文章
```

## `--to-zotero` 做什么

四件事，**每件都幂等**（同一批跑两遍 = 跑一遍）：

1. 取一份全库 DOI 索引查重（**不是按篇去搜** —— 按篇搜查不到刚写进去的，会建重复）
2. 库里没有 → 按 Crossref 元数据建条目，打上 `来源/自动` + `用途/建库`（或 `用途/精读`）
3. 挂正文 PDF；已经有 PDF 附件就不重复挂
4. 放进「`LLM导入`/`建库用`」或「`LLM导入`/`重点精读`」

**不打精读标签、不触发精读。** 那是花钱的事，什么时候开始由用户决定
（他在 Zotero 里打「待处理」，watcher 会接手）。

合集名可以在控制面板改（`GETPDF_COLLECTION_TOP`），改了不用动代码。

**为什么用途用合集、状态用标签**：进库原因是进来时就定了的、基本不变，适合合集；
处理状态会变（待处理 → 正文精读 → 全文精读 → 读完），而且 watcher 认的就是标签。

## 跑之前必须成立的两件事

1. **那台机器的出口 IP 得是机构的**（订阅权限靠 IP 生效，不是靠账号）。
   开了全局代理/VPN 会把出口换掉，权限当场失效。
2. **浏览器要带调试口启动，而且里面得有人过过一次人机验证**：
   ```
   msedge --remote-debugging-port=9333
   ```
   为什么必须是那一个：人机验证的通行证在它身上。新开一个干净的浏览器一样会被拦，
   而且拦住的时候没人在旁边点。

## 慢是故意的

默认每篇间隔 20 秒、单次最多 25 篇。出版商对短时间大量下载有风控，
**被掐的是整个机构的 IP**，代价由全校承担，不是某个账号被封那么简单。
要快得显式加 `--gap` / `--limit`。

## 拿不到的时候看 reason

| reason | 意思 | 该干嘛 |
|---|---|---|
| `captcha` | 撞上人机验证 | **停下来叫人去点**，点完重跑，已拿到的不会重下 |
| `no_access` | 这本刊没订 | 跳过，重试没用 |
| `no_pdf_link` | 出版商页面改版了 | 记进 INCIDENTS，回头改 `pdf_fetch` 的选择器 |
| `not_pdf` | 拿回来的不是 PDF | 多半是 captcha 的变种 |
| `exists` | 盘上已经有了 | 正常，跳过 |

## 附件必须走两步，少一步用户就打不开

```
upload_attachment(...)   ① 建附件条目，文件传进 Zotero 官方存储
put_local(att, pdf)      ② **把文件铺一份到本地 Zotero storage**
```

**②不是优化，是必需的。** 用户的文件同步走 WebDAV（坚果云），
桌面端**只会去 WebDAV 找文件**，官方存储里那份它不看 ——
少了②，条目有了、点开却是「在此路径无法找到附件」（2026-09-05 真坏过一次）。

②还顺带解决另外两件事：`find_pdf` 从本地 storage 读，下游解析/精读才有正文可读；
桌面端会把这个本地文件同步到用户自己的 WebDAV，跟他手动加的文献同一套。

`put_local` 住在 `shared.adapters.zotero_client`（`deepread` 也用它）。

## 存储余量

附件同时占 **Zotero 官方存储（免费 300 MB）**。PDF 一篇 1～9 MB，**几十篇就满**。
批量之前值得看一眼余量（zotero.org → Settings → Storage）。
满了的长期解法：升级 Zotero 存储，或者改成只铺本地、不传官方存储
（省配额，但要确认桌面端能把它同步出去）。
