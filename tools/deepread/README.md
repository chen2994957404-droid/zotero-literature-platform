# tools/deepread · 精读一篇文献

**一句话**：一篇 PDF → 一份中文图文精读报告，自动回写到 Zotero。
整个平台最常用、最有价值的一条线。

## 用户怎么用（推荐：一条命令都不用敲）

在 Zotero 里给文献打「待处理」标签 → 剩下全自动。
`watcher` 每 60 秒轮询一次，处理完把标签换成状态标签。服务已开机自启。

## 命令行

```
python -m tools.deepread KEY1 KEY2          批量正文精读
python -m tools.deepread --si KEY1          补 SI 精读 + 合并 + 回写
python -m tools.deepread --force KEY1       强制重跑（旧版自动备份 .bak）
python -m tools.deepread --rerun-pro        列出可用 pro 重跑的文献
python -m tools.deepread --rerun-pro 3      用 pro 重跑第 3 篇
```

常驻服务（自己的入口）：

```
python -m tools.deepread.watcher     盯 Zotero 标签，自动精读
python -m tools.deepread.watchdog    看门狗，watcher 真死了才重启它
```

## 状态标签（互斥，一篇同时只有一个）

`待处理`/`待精读` 触发 → `正文精读` / `全文精读`（正文+SI）/ `SI精读` / `无附件`

**已精读的部分不会重跑**：已有正文、后来补了 SI，就只补 SI 那段（省钱）。

## 产物

`workflow_data/library/<KEY>/`：`parsed/full.md`（解析全文）、
`summary.html`（中文精读）、`summary_full.html`（正文+SI 合并版）。

## 花钱吗

花。MineRU 解析额度 + 云端大模型长文输出，日常用 flash 省钱、
重要文献用 `--rerun-pro` 换 pro。**只允许在主力机上跑。**
