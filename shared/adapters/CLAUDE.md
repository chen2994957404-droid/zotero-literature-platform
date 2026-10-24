# adapters · 外接口环 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。

## 判据：什么东西该放这里

**「外部世界变了就得改它」的代码。** 每一块包住**一个**外部系统或持久化存储。

这一环就是架构准则【选型判据】说的那层皮：
> 「稳定的自己做（接口），发展中的用现成（实现）。」

外层是我们自己定义的函数名，多年不变；内层是随时可以整块换掉的第三方。
`pdf_parse` 是范例：外层 `parse_document` 没变过，内层是 MineRU 云端 API ——
换一家 PDF 解析服务只改这一个文件，上层代码一行不动。

## 一条特权，也是一条重责

**只有这一环允许联网、允许 import 第三方 SDK。**

这不是风格偏好 —— 它是「换掉 MineRU 只需改一个文件」这个承诺的**全部保证**。
如果 `tools/` 或 `host/` 也能直接发 HTTP 请求，那个承诺当场作废：
换服务时你得满仓库找 `urlopen`。守卫会强制这条（`python -m pytest`）。

## 现有成员

| 块 | 包住谁 | 谁在用 |
|---|---|---|
| `pdf_parse` | MineRU 云端 PDF 解析（另有本地快速文本层、docx 直读）| 落地流水线、取全文 |
| `embed` | 本机 Ollama 的 bge-m3 向量化 | 建向量库、库内检索 |
| `vectordb` | 向量库（当前实现 Chroma）| 同上 |
| `pdf_fetch` | 出版商全文：接管主力机「取全文用的浏览器」取 PDF / SI；也是下面各网页库共用的浏览器接管层 | 取全文、各网页库 |
| `crossref` | DOI 登记处：一个 DOI 的元数据、按题名找 DOI（免费）| 取全文、Claude Science |
| `unpaywall` | 一个 DOI 有没有合法的开放获取全文（免费，只要留邮箱）| 取全文 |
| `openalex` | OpenAlex：按 DOI 批量取作者 / 摘要；题名检索（免费 key 每天 $1）| 作者索引、Claude Science |
| `chemdb` | SciFinder / Reaxys：同一个浏览器里搜、读结果页文字（只读，人登录）| Claude Science |
| `pubchem` | PubChem 公开化合物库：CAS 号 → 结构式 | Claude Science |
| `polyinfo` | NIMS 聚合物数据库 PoLyInfo（只读，人登录，验证码人点）| Claude Science |
| `cnki` | 中国知网（学位论文 / 期刊 / 会议 / 中国专利；只读，学校 IP 授权，拼图人拖）| Claude Science |
| `ccdc` | CCDC Access Structures：单个晶体结构检索与详情（只读、不下 CIF）| Claude Science |
| `jcr` | Journal Citation Reports：一次查一本刊的 JIF / 分区 | Claude Science |
| `scopus` | Scopus：检索与「谁引用了它」列表（只读，一次一页）| Claude Science |
| `tansoole` | 探索平台（泰坦科技）：药品的品牌 / 规格 / 纯度 / 货期（价格是防抓取字体，不读）| Claude Science |

只有一个用户的 adapter 也住这里（下沉规则对 adapters 整环豁免）：把联网代码搬进工具会违反「联网只在 adapters」。

## 写一块新 adapter 的规矩

1. 对外只暴露**我们自己命名**的函数，不要把第三方的概念漏出去
   （例：`vectordb.query()` 返回拆平的结果，而不是 Chroma 那套「每字段套一层 list」）
2. 失败要抛 `shared.kernel.errors` 里的分类异常，让调用方知道**该不该重试**：
   限流 → `RateLimited`、服务没开 → `ServiceUnavailable`、密钥不对 → `AuthError`
3. 依赖只能向下（`shared.kernel`），不许 import `shared.domain` / `tools` / `host`
4. 必须带 `selftest.py`（架构准则铁律 3）

## 反面教材（阶段 2 修掉的）

同一个 OpenAlex API 曾被**三处各实现一遍**（雪球扩展 / 找新文献 / 方向地图，三样现在都已删掉）。
后果不只是重复：三份实现行为不一致（只有一份有退避重试），
而且**字段名各叫各的** —— 一处发 `cited_by`、一处读 `cited`，两边对不上，
于是走 OpenAlex 检索时引用数**永远是 0**，还连累了按被引排序的打分。

**同一个外部系统只能有一个 adapter。** 发现第二份，就是该合并的信号。
