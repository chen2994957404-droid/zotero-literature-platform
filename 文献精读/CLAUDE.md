# 文献精读 · 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这个文件夹是什么

把一篇文献（PDF）变成一份中文图文精读报告，并自动回写到用户的 Zotero 里。
**这是整个平台最常用、最有价值的一条线。**

用户是材料方向研究者（聚硼硅氧烷/动态键弹性体），**不懂编程**。
跟他讲话不要提技术细节，用大白话说结果。技术决策你自己拿主意。

## 用户怎么用它

在 Zotero 里给文献打「待处理」标签（打「待精读」也认）→ 剩下全自动。
`zotero_watcher.py` 每 60 秒轮询一次，发现就处理，处理完换成状态标签。

## 全自动流程（zotero_watcher.py 是总指挥）

```
打标签 → 找PDF → MineRU解析 → 精读正文 → (有SI就精读SI) → 合并 → 传回Zotero → 改标签
        find_pdf  mineru_parse  deepread_v4  si_deepread   merge_summary  upload_*
```

标签状态机（互斥，一篇文献同时只有一个状态）：
- `待处理`/`待精读` → 触发
- `正文精读`：只有正文被精读了
- `全文精读`：正文 + SI 都精读了
- `无附件`：没找到能精读的 PDF

**已精读的部分不会重跑**（省钱）。已有正文精读、后来补了 SI，只补 SI 那部分。

## 各文件职责

| 文件 | 干什么 |
|---|---|
| `zotero_watcher.py` | 总指挥：轮询标签、调度下面所有步骤、回写 Zotero |
| `watchdog.py` | 看门狗：watcher 卡死就重启（靠心跳文件判断） |
| `deepread_v4.py` | 精读正文 → 中文 HTML（含确定性插图） |
| `si_deepread.py` | 精读补充材料（SI），支持 PDF 与 .docx |
| `merge_summary.py` | 把正文精读 + SI 精读合并成一份 |
| `mineru_parse.py` | PDF → Markdown + 版面 JSON（调 MineRU 云服务） |
| `deepread_batch.py` | 批量精读，`--force` 可强制重跑（自动备份旧版 .bak） |
| `refresh_summary_file.py` | 把新版精读刷进 Zotero 本地 storage（不动条目，避免同步冲突） |
| `upload_summaries.py` / `zotero_upload_attachment.py` | 上传附件到 Zotero |
| `rerun_pro.py` | 用 pro 模型重跑某篇（更贵更准） |
| `_sys_prompt_v2.txt` | 精读的系统提示词，**改精读风格/结构就改这里** |

## 依赖的积木（在 ../modules/，本文件夹看不到）

`config`（密钥与本机设置）·`zotero_client`·`pdf_parse`·`llm_client`·`figure_crop`·
`si_filter`（SI 噪声过滤）·`proc_lock`（单实例锁）

**要改这些积木，请让用户改选 `modules/<积木名>` 那个文件夹。** 不要在这里重新实现它们。

## 血泪教训（改之前必读）

1. **max_tokens 必须给足**（现为 32000）。DeepSeek V4 思考模式默认开启，
   推理链**计入 max_tokens**；给 8000 会导致正文被截断甚至一个字都没有，
   产出「只有图没有文字」的废品。已加 `MIN_OK=3000` 底线：不达标直接失败退出，
   **宁可不产出，也不产出废品**（废品会被标成已精读，从此不再重跑）。
2. **不要「先删附件再传新的」**。删除动作会进 Zotero 同步链，导致反复弹冲突框。
   正确做法：复用已有附件条目，只覆盖文件内容。
3. **输入不要粗暴截断**。V4 有 1M 上下文，早期截到 40000 字符正好切掉结论与机理讨论。
4. 精读用 `deepseek-v4-flash`（输出长，用 flash 省钱）；pro 贵约 3 倍且规格相同。
5. 长任务会超过 MCP 的 60 秒调用上限 —— 用「后台发起 + 轮询文件结果」，别干等。

## 改完怎么验证

```
python ../平台管理/health_check.py        # 语法/导入/服务/数据 一次过
python deepread_batch.py <KEY> --force    # 拿真实文献实测（旧版自动备份）
```
判废标准：精读正文 < 3000 字基本是失败品，正常在 8000~13000 字。
