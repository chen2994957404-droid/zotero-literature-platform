# pdf_parse · PDF 解析基础件（公理层）

**公理**：PDF → 结构化文本(full.md) + 版面/图坐标(layout.json) + 图片。
精读 / 结构化抽取 / 向量化 三条定理都依赖它。底层用 MineRU 云端 API。

## 接口
```python
from adapters.pdf_parse import parse_pdf, is_parsed

parse_pdf("论文.pdf", "library/<key>/parsed")   # → 解析并落地；已解析则复用
is_parsed("library/<key>/parsed")               # → 是否已有解析结果
```

产出目录含：`full.md`（全文 Markdown）、`layout.json`（图坐标，裁图用）、
`images/`、`*_origin.pdf`（原PDF副本）。

## 配置
| 环境变量 | 必须 | 说明 |
|---------|------|------|
| MINERU_TOKEN | 是 | MineRU API token（不硬编码，需自行设置）|

MineRU 有每日免费额度（约 500 篇/天），解析零成本。

## 复用机制
`parse_pdf` 默认 `reuse=True`：目标目录已有 layout.json 就直接返回，不重复解析。
这实现了「精读与抽取共享解析结果，谁先跑谁生成」（数据契约）。

## 依赖
仅 Python 标准库。需联网（MineRU API）。

## 已固化的踩坑
- #1：PUT 上传不发 Content-Type 头（否则 OSS 签名不匹配）。
- #2：轮询字段是 `data.extract_result[0].{state,full_zip_url,err_msg}`，无 task_id 层。

## 自测
```
MINERU_TOKEN=... python adapters/pdf_parse/selftest.py
```
不实际解析（省额度），只验证：接口可导入、缺 token 正确报错、is_parsed 判断正确。
