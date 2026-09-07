# tools/extract · 结构化抽取

**一句话**：一批文献 → 统一 schema 的结构化字段 → 一张能横着比的对比表。

## 怎么用

```
python -m tools.extract <KEY>           只抽某一篇
python -m tools.extract                 抽所有未处理的（**全库作业**，花钱）
python -m tools.extract --rebuild       重抽全部（覆盖前自动备份）
python -m tools.extract --parse         缺 full.md 的先 MineRU 解析
python -m tools.extract --coarse        粗层全库（本地模型，零成本）
python -m tools.extract --si-pending --list   只列「有 SI 却没读 SI」的，不花钱
python -m tools.extract --local         改用本地 Ollama（零花费，准确度低一档）
```

另外两个独立入口：

```
python -m tools.extract.wizard          重抽向导（给用户双击的「重抽缺SI的文献.bat」）
python -m tools.extract.compare_models  比一比两个模型（只读不写）
```

## 两档数据

| 档 | 料从哪来 | 用什么模型 | 用途 |
|---|---|---|---|
| 精层 | 精读产物 `parsed/full.md`（+ SI）| 云端 pro | 可信数值，能进论文 |
| 粗层 | Zotero 自带全文索引 | 本地 qwen | 广撒网、粗筛 |

## 产物

- `data/serving/structured/<KEY>.json` —— 每篇的结构化字段
- `data/serving/structured/compare.md` —— 研究论文横向对比表（找 idea 的主载体）
- `compare_reviews.md` / `compare_PBS.md` —— 综述单列 / 聚硼硅氧烷精层子表

抽完会自动重建 `paperdb` 的查询库。

## 自带一道自检

抽完会拿原文回查一遍：漏抽的补、编出来的删（`extract_with_eval`）。
所以一篇会调不止一次模型。

## 语言

**输出原生英文**，不翻译 —— 这是给机器和下游 LLM 用的中间数据（见根目录 CLAUDE.md 的语言约定）。

## 抽完怎么验（不花钱）

```
python -m tools.extract.audit                  # 全库抽检：数字回原文找得到吗
python -m tools.extract.audit --key ABCD1234   # 看某一篇具体哪些对不上
```

把抽出来的每个数字回原文逐字找一遍。找不到的挑出来排序，
人看最可疑的几篇就够 —— 比「每篇都让模型自检一轮」省两倍多的钱。

⚠ **找不到 ≠ 编的**：单位换算（1.5×10^4 vs 15000）、把 90% 写成 0.9 都会算成没找到。
看的是排序和具体内容，一眼能分出是换算还是瞎编。
