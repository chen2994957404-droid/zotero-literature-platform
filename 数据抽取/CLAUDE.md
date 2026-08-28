# 数据抽取 · 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这个文件夹是什么

把每篇文献的关键信息抽成**结构化字段**（材料体系、动态键类型、合成条件、性能数值、
机理、局限……），再汇总成一张横向对比表。用途是「竖着比同一字段，找矛盾、空白、规律」——
这是用户找研究方向和空白点的主要依据。

用户是材料方向研究者（聚硼硅氧烷/动态键弹性体），**不懂编程**。

## 语言约定（重要，别改错）

**抽取出的数据保持英文原生**，不翻译。因为用户本来就读英文文献，
而这些数据是给大模型做关联分析用的中间产物。
（对比之下：精读报告和问答答案是给用户看的，用中文。）

## 各文件职责

| 文件 | 干什么 |
|---|---|
| `extract_structured.py` | 核心：一篇文献 → 结构化 JSON（schema 定义在这里） |
| `extract_batch.py` | 批量抽取，需要时自动先调 MineRU 解析 |
| `extract_library.py` | 对整个 library 跑抽取 |
| `filter_domain.py` | 按领域筛选文献 |

产物：
- `workflow_data/structured/<KEY>.json` —— 每篇的字段
- `workflow_data/structured/compare.md` —— 横向对比表（研究论文）
- `compare_reviews.md`（综述单列）、`compare_PBS.md`（聚硼硅氧烷精层，含真实数值）

## 依赖

- **积木**（`../modules/`）：`llm_client`、`config`、`pdf_parse`
- **跨文件夹调用**：解析脚本在 `../文献精读/mineru_parse.py`
- 模型：`deepseek-v4-pro`（抽取输出少、要准，用 pro 几乎不增成本）

**要改积木请让用户改选 `modules/<积木名>` 文件夹。**

## 血泪教训

1. **不要用本地 7B 模型做抽取**。实测它会把分子量 3.0 错配成「复数黏度 3.0 Pa·s」，
   产生看似合理实则错误的脏数据。必须用 DeepSeek。
2. **schema 字段说明不要只举力学例子**。早期 `characterization` 只举力学例子，
   导致模型忽略光谱/热分析，N/A 率高达 61%；放宽为「任何量化表征结果」后降到 47%。
3. `--rebuild` 会覆盖已有结果，**精层数据（如 compare_PBS）有 protected 保护**，别绕过。
4. 全库重抽要花钱（175 篇 × API），**动手前先问用户**。

## 改完怎么验证

```
python extract_structured.py <KEY>          # 单篇验证，看字段是否合理、N/A 是否偏多
python ../平台管理/health_check.py
```


## 查询库（2026-08-28 新增）

`compare.md` 是给人竖着看的表，不能筛、不能分组、性能数值比不了大小。
所以 `structured/*.json` 现在还会建成一个 SQLite 查询库：

```
python 数据抽取/查询库.py --rebuild                     # 重建（抽取 CLI 已自动带上）
python 数据抽取/查询库.py --stats                       # 各档次 × 各字段有值率
python 数据抽取/查询库.py --find boron --prop tensile --min 10
python 数据抽取/查询库.py --sql "SELECT tier, COUNT(*) n FROM papers GROUP BY tier"
```

逻辑在 `pipelines/paper_db`（那儿有完整说明）。
**库是索引不是真相** —— 真相是 JSON，库随时可删可重建。
