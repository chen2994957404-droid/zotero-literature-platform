# zotero_client · Zotero 接口基础件

平台的「基础件」之一——封装与 Zotero 的所有交互。下游模块（精读/结构化抽取/向量化）
都通过它读文献、定位正文 PDF，不再各自拷贝逻辑。

## 为什么存在
消除技术债：`find_pdf` 曾在 zotero_watcher.py、extract_batch.py 各有一份拷贝，
改一处要同步另一处（易漏，正文/SI 判定曾出 bug，见踩坑 #15）。收敛成单一实现。

## 接口
```python
from modules.zotero_client import find_pdf, get_fulltext, zget

find_pdf("2T6H4S3D")                    # → 正文 PDF 本地路径（自动排除 SI）
find_pdf("2T6H4S3D", return_att_key=True)  # → (path, att_key)
get_fulltext(att_key)                   # → Zotero 全文索引文本（粗层用）
zget("/users/<id>/items/<key>/children")   # → 本地只读 API
```

## 配置（走 `modules.config`，在控制面板里填，**不要写死在代码或文档里**）
| 变量 | 示例 | 说明 |
|------|------|------|
| ZOTERO_USER_ID | `12345678` | Zotero 设置→账户里的 userID，纯数字 |
| ZOTERO_STORAGE | `D:\Zotero\storage` | 附件存储目录 |
| ZOTERO_API_HOST | `http://localhost:23119` | 本地 API 地址，一般不用改 |

必填项缺失时 `config.need_site()` 会明确报错并告知怎么配 ——
**刻意不留「读不到就用默认值」的兜底**：那会把开发者本人的用户 ID 留在源码里，
且别人装上后会静默连到陌生人的库。

依赖：仅 Python 标准库（urllib/json/re/os）。需 Zotero 桌面开着。

## 自测
```
python modules/zotero_client/selftest.py
```
用已知有正文的 key 验证 find_pdf 正确选中正文（非 SI）。

## 正文/SI 判定规则（find_pdf）
1. 优先 `title=='Full Text PDF'` 的规范正文（最可靠信号）。
2. 兜底：非补充材料附件里选文件最大的。
3. SI 识别：文件名或 title 命中 SUPP_PAT（含 Springer MOESM/ESM），或 title=='SI'。
