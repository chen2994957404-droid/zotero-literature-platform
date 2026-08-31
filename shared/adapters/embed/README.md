# embed · 文本向量化基础件（公理层）

**公理**：文本 → 向量（bge-m3 本地嵌入），+ 向量化前的文本预处理（去参考文献、切块）。
向量问答线依赖它。embedding 只做映射不理解内容——区别于 llm_client 的生成。

## 接口
```python
from adapters.embed import embed, strip_references, chunk

chunk(full_md_text)          # → 文本块列表（按段落，去参考文献+图片标记）
embed(["文本1", "文本2"])    # → [向量1, 向量2]
strip_references(text)       # → 去掉参考文献后的正文
```

## 为什么存在
embed / strip_references / chunk 此前在 vectorize.py 和 vectorize_library.py
各有一份重复。收敛成单一公理件，一处正确处处复用。

## 配置
| 环境变量 | 默认 | 说明 |
|---------|------|------|
| EMBED_MODEL | bge-m3 | 嵌入模型（本地，1024维，中英都强）|
| OLLAMA_HOST | http://localhost:11434 | Ollama 地址 |

## 设计要点
- 去参考文献：向量化前截掉 References 部分，避免检索命中一堆文献列表标题。
- 防误截：若截后正文<20%，退回原文（匹配可能出错）。
- 本地免费：bge-m3 跑在本地 Ollama，向量化零成本。

## 依赖
Python 标准库。需本地 Ollama 跑着 bge-m3。

## 自测
```
python adapters/embed/selftest.py
```
用本地 bge-m3（零成本）验证 embed 返回向量、chunk/strip_references 正确。
