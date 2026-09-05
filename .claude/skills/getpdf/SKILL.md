---
name: getpdf
description: 一批 DOI → 把正文 PDF 取到手（借真实浏览器，用机构订阅权限）。什么时候用：用户说「把这几篇下下来」「这批的正文我要」；discover 找出了该读的清单，下一步是把正文弄到手；要精读某篇，但 library 说库里没有 PDF
---

<!-- 本文件由 host/codegen/skills.py 生成，**别手改**。改源：tools/getpdf/SKILL.md + tools/getpdf/tool.toml -->

> **动手之前先看这三行**（取自 `tools/getpdf/tool.toml`）：
> 不花钱 · **有副作用**：向出版商网站发真实请求 —— 量大会触发风控，被封的是整个机构的 IP、写 data/raw/_incoming/getpdf/*.pdf · 任何机器都能跑
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
```

## 跑之前必须成立的两件事

1. **那台机器的出口 IP 得是机构的**（订阅权限靠 IP 生效，不是靠账号）。
   开了全局代理/VPN 会把出口换掉，权限当场失效。
2. **浏览器要带调试口启动，而且得是主人平时看文献的那个**：
   ```
   msedge --remote-debugging-port=9222
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

## 现在还不做的事

**不写 Zotero。** PDF 落在 `data/raw/_incoming/getpdf/`，还得人工导进去。
原因是 `zotero_client` 目前只读，没有建条目/挂附件的能力 ——
那要新加适配件，是下一步，不在这里凑合。
