# paper_discovery · 文献发现基础件（公理层）

**公理**：检索词 → 相关文献列表（去 OpenAlex 搜，标记库里已有）。
用途聚焦：**方向补库**——找某方向所有相关文献，供筛选/导入 Zotero。

升级自早先的 find_papers.py（散脚本 → 干净可复用公理件，返回结构化数据而非打印）。

## 接口
```python
from pipelines.paper_discovery import search

results = search("polyborosiloxane self-healing", limit=25)
# → [{title, doi, year, first_author, venue, abstract, cited_by, is_oa, in_library}, ...]
# in_library=True 表示库里已有（去重用）
```

## 依赖
Python 标准库 + zotero_client（查库里已有，用于去重标记）。
OpenAlex 免费、无需 key。Zotero 没开时 in_library 全 False（不影响搜索）。

## 设计
- OpenAlex 数据源：覆盖广、免费、含摘要/引用数/OA状态。
- 去重标记：对照 Zotero 库的标题（归一化）+DOI，标 in_library。
- 摘要还原：OpenAlex 用倒排索引存摘要，已还原成正常文本。

## 未来扩展（采购清单）
- related(doi)：Semantic Scholar 引用网络（找引用它的/它引用的/相似的）——顺藤摸瓜用。
- 自动导入 Zotero：需走 Zotero Web API（本地API只读，踩坑#8）。

## 自测
```
python pipelines/paper_discovery/selftest.py
```
用真实检索词验证返回结构正确、字段完整。
