# ner · 零样本命名实体识别（包 GLiNER）

> 你可能是被单独选中这个模块文件夹打开的。本文件是你的全部上下文。

## 这是什么

一个原子模块：一段英文 + 几个标签名（sample code / material / reagent）→ 标出来的实体。
不用训练，medium 版 CPU 0.2 s/句。给抽取的「这个数是哪个样品的」提供封闭的样品名单。

## 对外接口

| 函数 | 说明 |
|---|---|
| `entities(text, labels, threshold)` | 原始实体列表（含位置与分数） |
| `sample_mentions(text)` | 窗口里的样品 / 材料名，去重去噪 |
| `alive()` | 模型能否加载 |

模型名配置项 `NER_MODEL`（默认 `urchade/gliner_medium-v2.1`），首次用要下载约 1 GB。

## 验证

`python shared/adapters/ner/selftest.py`（纯逻辑）· `--live` 真加载模型。
