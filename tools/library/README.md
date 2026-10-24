# tools/library · 查证据库

**一句话**：有没有这篇、手上有什么、按条件检索、按研究团队看、读某一节原文 —— 全部只读、免费、秒回。
（2026-10-13 起 Zotero 移出平台，原来查 Zotero 的命令都删了。日常检索请用桌面上的「文献库」应用，同一套。）

## 怎么用

```
python -m tools.library 库                          # 证据库有多大
python -m tools.library 库 硼                        # 按标题 / DOI / 期刊搜
python -m tools.library 检索 10.1021-acs.macromol    # DOI（可以只写一部分、斜杠横杠都行）
python -m tools.library 检索 --通讯 武培怡 --年 2024-2026
python -m tools.library 检索 polyborosiloxane --摘要 --有 si
python -m tools.library 团队                         # 研究团队 + 每组篇数
python -m tools.library 团队 武培怡                   # 一个组：大导 / 小导 / 已独立 + 文章
python -m tools.library 找 "boronic ester exchange"  # 库内按意思找段落（零成本）
python -m tools.library 引文 doi_10.1021-acs.macromol.6c00733   # 参考文献，标出库里已有的
python -m tools.library 盘点                         # 库里有什么：正文 / SI 三态 / 已解析
```

## 它不做什么

库里没有的去取 → `getpdf`；综合回答、比数值、读曲线 → 交给 Claude Science（它通过 `/science` 接口读这里）。

## 保证

只读。「检索 --建索引」（取一次 OpenAlex 作者与摘要，免费额度）和「团队 --重建」只写可重建的索引。
