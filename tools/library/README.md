# tools/library · 查我的 Zotero 库

**一句话**：搜条目、看合集标签、拿正文 PDF 与全文 —— 全部只读、免费、秒回。

## 怎么用

```
python -m tools.library stats                       # 库有多大 + Zotero 通不通
python -m tools.library search 聚硼硅氧烷 --limit 10  # 搜标题作者年份
python -m tools.library search 硼 --all              # --all = 连全文一起搜（更广更吵）
python -m tools.library search --tag 待处理          # 按标签
python -m tools.library item ABCD1234                # 单篇完整信息
python -m tools.library pdf ABCD1234                 # 正文 PDF 在哪（自动排除 SI）
python -m tools.library fulltext ABCD1234 --max 5000 # 正文全文
python -m tools.library collections                  # 合集树
python -m tools.library tags                         # 标签及篇数
python -m tools.library recent --days 30             # 最近 30 天新增/改动
```

## 跟另外两个「查库」的分别

| 想干什么 | 用谁 | 花钱吗 |
|---|---|---|
| 库里有没有标题带「boron」的？最近加了什么？ | **library** | 不 |
| 我库里关于自修复机理有什么？（要一段中文回答）| `ask` | 花 |
| 拉伸强度 > 10 MPa 的体系有哪些？ | `paperdb` | 不 |

## 前提

Zotero 桌面开着，且在「设置 → 高级」里勾了
「允许其他应用与本机上的 Zotero 通信」。没开就只会告诉你连不上，不会报错崩掉。

## 保证

**一个字节都不会写进 Zotero。** 没有任何写操作、没有删除、不改标签。
要改库房请用 `tools/curate`（那边每一步都要人先确认）。
