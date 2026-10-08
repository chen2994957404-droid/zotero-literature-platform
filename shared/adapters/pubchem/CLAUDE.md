# pubchem · PubChem 公开化合物库

> 你可能是被单独选中这个模块文件夹打开的，看不到项目其他部分。本文件是你的全部上下文。

## 这是什么

**一个原子模块**：CAS 号 → 结构式（SMILES）、分子式、PubChem CID。免费、不要密钥。

## 为什么存在（2026-10-08）

Reaxys 里 CAS 号登记不全：硼酸 10043-35-3 在 Reaxys 只挂在 7 个矿物 / 水合物条目上，主条目没登记这个号，
按 CAS 号查 Reaxys 落不到主条目（Claude Science 实测报的）。`host/mcp/science.py` 在 Reaxys 按 CAS 号查文献、
而 Reaxys 给的候选文献都很少时，用这里把 CAS 号换成结构式，再让 `chemdb` 按原样结构搜。

## 对外接口

| 函数 | 说明 |
|---|---|
| `cas_to_structure(cas)` | → `{cid, smiles, formula}`；PubChem 没这个号 → `None`；对方出错抛 `PubChemError`（可重试） |
| `pick_smiles(props)` | 属性字典里取 SMILES —— 字段名 2025 年前后换过（实测返回 `SMILES`，老文档写 `IsomericSMILES`），几种都认 |

## 谁在用

- `host/mcp/science.py`（Reaxys 的 CAS 号兜底）

## 自测

`python shared/adapters/pubchem/selftest.py`（离线）；`--live` 真查一次硼酸（CID 7628）。
