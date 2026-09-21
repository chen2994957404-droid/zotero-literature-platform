# sentences · 句子切分（包 pySBD）

> 你可能是被单独选中这个模块文件夹打开的。本文件是你的全部上下文。

一个原子模块：英文段落 → 句子（带字符位置）。Fig. / ref. / et al. / vs. / e.g. 这类缩写不当句尾。
使用者：`tools/extract`（找数所在句）、`tools/extract/zoning`。

| 函数 | 说明 |
|---|---|
| `split(text, lang='en')` | → `[(start, end, sentence)]` |
| `sentence_at(text, pos)` | 包含 pos 的那一句 |

验证：`python shared/adapters/sentences/selftest.py`。依赖 `pysbd`。
