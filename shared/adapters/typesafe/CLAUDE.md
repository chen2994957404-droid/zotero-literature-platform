# typesafe · Jev 判断模型

> 你可能是被单独选中这个模块文件夹打开的。本文件是你的全部上下文。

## 这是什么

一个原子模块：一段文字（state）+ 若干「真假 / 选一个 / 打分」题 → 答案 + 概率 + 置信度。
**它不写字**，只做判断；给排序、分类、核对这类环节用。2026-09-19 起试用，没有公开评测，
好不好靠平台自己的对照实验说话。

## 对外接口

| 函数 | 说明 |
|---|---|
| `ask(state, questions, purpose=)` | 多题一次问；走当日额度闸、记账（通道 `typesafe`） |
| `noul(state, instructions)` | → 0–1 真假可信度 |
| `choice(state, instructions, {选项:说明})` | → `(选中, 概率分布, 置信度)` |
| `score(state, instructions, [档位...])` | → `(分数, 概率分布, 置信度)` |
| `build_questions` / `parse_answers` | 纯函数，自测用 |

密钥 `TYPESAFE_KEY`；没填抛 `ConfigError`。限制：纯文字、state ≤32k token、英文最准。

## 谁在用

- 暂无（试用阶段；第一个候选是 `tools/discover` 的相关性排序对照）

## 改完必须做

```
python shared/adapters/typesafe/selftest.py           # 离线
python shared/adapters/typesafe/selftest.py --live    # 真敲一次（花钱，几分之一分）
python -m pytest -q
```
