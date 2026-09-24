# stopwords · 英文停用词表（原样收录）

> 你可能是被单独选中这个文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这是什么

**一个原子模块**，住在 `shared/domain/`（纯逻辑层）：Glasgow IR 组的 318 词英文停用词表，
即 scikit-learn 的 `ENGLISH_STOP_WORDS`，2026-09-24 原样导出。**不手改** —— 用户定的规矩是词表找现成资源，别碰到一个补一个。

## 谁在用

- `tools/extract/fine_fact`：数后面的词是停用词就不当单位（Pint 会把 in 读成英寸、a 读成年）
- `tools/litsearch/session`：挖新检索词时词组首尾不许是停用词

## 对外接口

| 名字 | 说明 |
|---|---|
| `ENGLISH_STOP_WORDS` | frozenset，318 个小写英文词 |

## 验证

```
python shared/domain/stopwords/selftest.py
```
