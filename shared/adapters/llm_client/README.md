# llm_client · LLM 调用基础件（公理层）

**公理**：文本 → LLM → 文本 / JSON。统一封装对大模型的调用，
支持云端 DeepSeek 和本地 Ollama。

## 为什么存在
此前 LLM 调用散在 9 个脚本、6 个函数各写各的，导致重复 + 密钥注入混乱（踩坑 #17）。
收敛成单一公理件：一处正确，处处复用。

## 接口
```python
from adapters.llm_client import chat, chat_json

# 纯文本（对话/精读/问答）
chat(system, user)                          # 默认 deepseek-v4-pro
chat(system, user, model='deepseek-v4-flash')  # 精读用 flash（输出多、省钱）

# 强制 JSON（结构化抽取）
chat_json(system, user)                     # 返回 dict，temperature 默认 0.1 求稳
chat_json(system, user, provider='ollama')  # 本地 qwen 抽取
```

## 配置（环境变量，可被参数覆盖）
| 变量 | 默认 | 说明 |
|------|------|------|
| DEEPSEEK_KEY | (无) | DeepSeek key |
| LLM_PROVIDER | deepseek | 默认 provider（deepseek/ollama）|
| DEEPSEEK_MODEL | deepseek-v4-pro | 云端默认模型 |
| OLLAMA_MODEL | qwen2.5:7b-instruct | 本地默认模型 |
| OLLAMA_HOST | http://localhost:11434 | Ollama 地址 |

## 模型选择原则（宪法沉淀）
输出少的活用 pro（结构化抽取，输出仅十几字段）；输出多的用 flash（精读，9000字长文）。
pro/flash 主要差在输出价，输出轻则 pro 几乎不增成本却更准。

## 依赖
仅 Python 标准库。DeepSeek 需联网+key；Ollama 需本地服务。

## 自测
```
python adapters/llm_client/selftest.py
```
用本地 Ollama（零成本）验证 chat / chat_json 能正常返回；缺 key 时 deepseek 正确报错。
