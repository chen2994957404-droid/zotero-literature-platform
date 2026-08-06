# 库内问答 · 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这个文件夹是什么

让用户能用大白话问自己的文献库：「我库里关于 B–N 配位有什么？」
做法是 RAG：把精读过的文献切块向量化存进本地向量库，提问时检索最相关的几块，
交给大模型结合这些片段作答，并附上来源文献。

用户是材料方向研究者（聚硼硅氧烷/动态键弹性体），**不懂编程**。答案用中文。

## 各文件职责

| 文件 | 干什么 |
|---|---|
| `ask.py` | 提问入口。`ask_answer(q)` 返回 `{answer, sources, chunks}`；`ask()` 是命令行打印版 |
| `vectorize.py` | 把文本切块 → 向量 → 存入 ChromaDB |
| `vectorize_library.py` | 把 `workflow_data/library/` 里已精读的文献批量入库 |

用法：`python ask.py "你的问题"`，不带参数进交互模式。

## 依赖

- **积木**（在 `../modules/`，本文件夹看不到）：`embed`（文本→向量，本地 bge-m3）、
  `llm_client`（调大模型）、`config`（密钥）
- **本地 Ollama 必须在跑**：向量化依赖它。不通就 `Start-ScheduledTask -TaskName OllamaService`
- **向量库**：`workflow_data/vector_db/`（约 9000+ 文本块）

**要改这些积木，请让用户改选 `modules/<积木名>` 文件夹。**

## 注意事项

1. **向量化用本地模型 `bge-m3`（免费），回答用云端 flash**。别把向量化换成云端，
   几千篇文献的量级会很贵，而且本地效果够用。
2. **Ollama「失明」问题**：Ollama 启动时若没拿到 `OLLAMA_MODELS` 环境变量，
   模型列表会返回空，表现为问答报错。开机自启任务里已固化该变量。
   排查第一步：`Invoke-RestMethod http://localhost:11434/api/tags` 应返回 4 个模型。
3. `ask.py` 的逻辑与打印是分开的（`ask_answer` 只算不打印），
   要在别处复用问答能力就调 `ask_answer`，**不要复制粘贴逻辑**。
4. 新精读的文献不会自动进向量库，需要跑 `vectorize_library.py`。

## 改完怎么验证

```
python ask.py "聚硼硅氧烷的动态键是什么"
```
正常应返回中文答案 + 2 个以上来源。返回 `chunks=0` 说明向量库空或没检索到。
