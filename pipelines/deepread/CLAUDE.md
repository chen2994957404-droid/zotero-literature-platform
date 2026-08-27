# pipelines/deepread · 精读编排 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。

## 这块是什么

**一个 Zotero item key → 一份中文图文精读。**平台最有价值的那条线的编排。

```
key → 找PDF → MineRU解析 → 正文精读 → (有SI就精读SI) → 合并 → Result
      adapters  adapters    本包       本包            本包
      zotero    pdf_parse   main_text  si             merge
```

调用方（`文献精读/zotero_watcher.py`）只写一行：

```python
from pipelines import deepread
r = deepread.run(key, item=item, provider='deepseek', model=MODEL, llm_key=KEY)
r.state        # 'full' / 'main' / 'si' / 'nopdf' / 'failed'
r.final_html   # 该拿去回写 Zotero 的那份
```

## 三条铁的约定（改之前先看懂为什么）

1. **不写 Zotero、不改标签。**编排环只产出文件；`r.state` 是「实际做成了什么」
   这个**事实**，翻译成标签是 watcher 的事（也是两台机器分工的闸门所在）。
2. **不抛异常。**单步失败记在 `Result.steps` 里，别的步骤照做 ——
   SI 挂了不该让已经花了钱的正文精读白做。
3. **幂等。**每一步先问 `core.jobs`「做过没有、产物还在不在、版本够不够新」，
   做过就跳过。这是省 MineRU + DeepSeek 的钱的地方，别顺手改掉。

## 文件

| 文件 | 干什么 |
|---|---|
| `__init__.py` | `run()` 状态机：谁在什么条件下被调、失败了怎么办 |
| `main_text.py` | 正文精读：元数据 → 裁图 → LLM → 确定性插图 → HTML |
| `si.py` | SI（补充材料）精读，支持 PDF 与 .docx |
| `merge.py` | 正文 + SI 合并成一份 |
| `_sys_prompt_v2.txt` | **精读的系统提示词，改精读风格/结构就改这里** |
| `selftest.py` | 离线自测（不花钱、不联网） |

## 版本号：改了提示词一定要 +1

`main_text.PROMPT_VER` / `si.PROMPT_VER` 会随每份产物记进状态库。改了提示词范式
却不改版本号，等于告诉系统「旧产物还是新的」，`jobs.stale()` 就查不出待重跑清单。

```python
jobs.stale('main_summary', prompt_ver=3)   # 提示词升到 v3 后，谁该重跑
```

## 血泪教训（继承自 deepread_v4，一条都别忘）

1. **max_tokens 必须给足**（32000 起）。DeepSeek V4 的推理链计入 max_tokens，
   给 8000 会产出「只有图没有文字」的废品。`MIN_OK=3000` 是底线：
   不达标就抛 `DeepreadFailed`、**不写盘** —— 废品一旦落盘会被标成已精读，从此不再重跑。
2. **输入不要粗暴截断**。V4 有 1M 上下文；早期截到 40000 字符正好切掉结论与机理讨论。
3. **裁图不要自己重写**。用 `domain.figure_crop` —— 踩坑 #7 的全部智慧固化在那儿
   （用坐标从原 PDF 裁完整图、page_size 做缩放基准、三类视觉块合并、纵向聚类）。
4. **插图是脚本干的，不是模型干的**。模型只输出【图N】标记，图由 `insert_figures` 插。

## 还没搬进来的（阶段 3 剩余）

- **结构化抽取**（`数据抽取/extract_structured.py`）仍由 watcher 用子进程拉起。
  它是精读之后的一步，本身也该成为一个 pipeline。
- **回写 Zotero**（`zotero_upload_attachment.py` / `upload_summaries.py`）
  该收进 `adapters/zotero_client`，watcher 才能瘦成「看标签 → 入队 → 完事」。
