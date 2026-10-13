# tools/deepread · 精读一篇文献

**一句话**：一篇 PDF → 一份中文图文精读报告（存在证据库那篇的目录里）。
整个平台最常用、最有价值的一条线。

## 用户怎么用（推荐：一条命令都不用敲）

在桌面「文献库」里打开这篇，点「精读这篇」→ 确认 → 排队跑完，详情页出现精读按钮。
（2026-10-13 起 Zotero 移出平台：不再打标签触发、不再回写 Zotero。）

## 命令行

```
python -m tools.deepread KEY1 KEY2          批量正文精读
python -m tools.deepread KEY1 --si          补 SI 精读 + 合并
python -m tools.deepread --force KEY1       强制重跑（旧版自动备份 .bak）
python -m tools.deepread --rerun-pro        列出可用 pro 重跑的文献
python -m tools.deepread --rerun-pro 3      用 pro 重跑第 3 篇
```

## 做成什么

`正文精读` / `全文精读`（正文+SI）/ `SI精读` / 没文件就做不了

**已精读的部分不会重跑**：已有正文、后来补了 SI，就只补 SI 那段（省钱）。

## 审稿（写完自动跑）

精读写完，另一个模型对着原文逐句判：编造 / 曲解 / 漏重点。不过 → 带着意见把那几栏回炉一次 → 复审。
两轮仍不过的标 `needs_human`，其余不经人手。报告：`data/curated/<KEY>/review.json`。

```
python -m tools.deepread KEY1 --审稿                审一篇已有的精读
python -m tools.deepread --审稿校准 --篇数 10       拿范文校准审稿：干净范文误报率 + 故意塞错的查全率
```

## 产物

`data/raw/<KEY>/parsed/full.md`（解析全文）、`data/curated/<KEY>/`：
`summary.html`（中文精读）、`summary_full.html`（正文+SI 合并版）。

## 花钱吗

花。MineRU 解析额度 + 云端大模型长文输出，日常用 flash 省钱、
重要文献用 `--rerun-pro` 换 pro。**只允许在主力机上跑。**
