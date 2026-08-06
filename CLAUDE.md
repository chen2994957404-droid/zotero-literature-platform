# 文献自动化科研平台 · 给 Claude 的说明

围绕 Zotero 的文献科研平台。用户是材料方向研究者（聚硼硅氧烷/动态键弹性体），**不懂编程**。
本文件是**唯一入口**：想帮用户干活看【第一部分】，想改代码看【第二部分】。

## ⚠ 先看目录结构（2026-08-06 重组）

项目按功能分成若干文件夹，**每个文件夹里都有自己的 `CLAUDE.md`**：

```
文献精读/  库内问答/  数据抽取/  找新文献/  库房维护/  平台管理/  归档_旧版本/
modules/   ← 10 块公理件，每块也有自己的 CLAUDE.md
```

**如果用户只选中了某一个文件夹跟你对话，那个文件夹的 CLAUDE.md 就是完整上下文。**
在根目录（现在这里）时，你能看到全部，负责跨文件夹的改动与全局判断。

用户的操作入口是根目录的 **控制面板.bat**（本地网页）：
看服务状态/进程/日志、改密钥与模型、重启后台服务。
人看的地图在 `项目导览.md`。

---

# 第一部分 · 能力速查（用户提科研需求时看这里）

**用户不懂代码，别跟他讲技术细节。他说需求，你选工具执行，用大白话汇报结果。**

## 用户可能提的需求 → 你该用什么

| 用户说 | 你怎么做 |
|--------|---------|
| "我库里关于XX有什么？" "帮我查查XX" | `python 库内问答/ask.py "问题"`（RAG 问答，中文答+附来源）|
| "帮我找XX方向的文献" "补充点XX的文献" | `modules/paper_discovery` 的 `search(query)`，返回文献列表并标记库里已有 |
| "帮我横向比较XX" "这方向有什么规律/空白" | 读 `workflow_data/structured/compare.md`（研究论文横向对比表，148篇）；PBS 方向另有 `compare_PBS.md` |
| "精读某篇文献" | 让他在 Zotero 打「待处理」标签即可。**状态机自动判断**：只有正文→精读正文→标「正文精读」；有SI→连SI实验细节一起精读并合并→标「全文精读」；已精读过的只补缺的部分不重跑。服务已开机自启。 |
| "把某批文献的数据抽出来" | `python 数据抽取/extract_batch.py KEY1 KEY2`（自动 MineRU 解析+DeepSeek 精抽）|
| "把论文图里的曲线变成数据" | `modules/chart_digitize` 的 `digitize()`，**必须用云端大模型**（硅基流动 Qwen3.5-397B/3.6-27B），本地7B会编假数据 |
| "帮我想想研究方向/idea" | 读 compare 表做横向关联分析（找机理×性能的空白格），或 `python 找新文献/brainstorm.py` |

## 现成数据资产（在哪找什么）

- `workflow_data/structured/compare.md` — 148篇研究论文横向对比表（材料/动态键/合成/性能/机理）
- `workflow_data/structured/compare_reviews.md` — 5篇综述单列
- `workflow_data/structured/compare_PBS.md` — 聚硼硅氧烷方向精层子表（10篇，含真实数值）
- `workflow_data/structured/<KEY>.json` — 每篇的结构化字段
- `workflow_data/library/<KEY>/` — 精读过的文献（parsed/full.md 全文 + summary.html 中文精读）
- `workflow_data/vector_db/` — 向量库（9105块，供 库内问答/ask.py 检索）

## 10 块公理件（modules/，可直接 import 复用）

`config`（密钥统一加载）· `zotero_client`（定位文献/正文PDF）· `pdf_parse`（PDF→文本）
`llm_client`（调LLM，含视觉）· `embed`（文本→向量）· `figure_crop`（裁完整Figure）
`chart_digitize`（图表→数据点）· `paper_discovery`（找文献补库）· `si_filter`（SI噪声过滤）
`proc_lock`（单实例锁，防同一服务跑两份）

改动后跑 `python modules/<名>/selftest.py` 验证单块；
**改完务必跑一键体检**：`python 平台管理/health_check.py`（语法/密钥安全/配置/服务/自测/数据/后台一次过）。

## 语言约定（重要）

- **给用户看的用中文**：精读 HTML、问答答案。
- **机器数据用原生英文**：结构化抽取、图表数据（用户读英文文献，中间数据给LLM用，不翻译）。

## 运维现状（不用管，已自动化）

两个自启任务（登录 + 每小时保活）：
- `ZoteroLiteratureWatcher` → 看门狗 → watcher：用户打「待处理」标签即自动精读，卡死自动重启、无窗口。
- `OllamaService` → 本地 Ollama（问答/向量化依赖它），带正确 `OLLAMA_MODELS` 路径。

**密钥管理（2026-07-26 安全化后）**：源码内**不含任何明文密钥**。
统一走 `modules/config` 的 `get_key()`，加载顺序：环境变量 → 项目根 `.env` 文件。
`.env` 已在 .gitignore（不进版本库），模板见 `.env.example`。
好处：不再受"setx 只对新进程生效"之苦（该坑曾致 401/SI解析失败三次）。

**问答（ask.py）报错时先查这两条**：
1. Ollama 在跑吗？`Invoke-RestMethod http://localhost:11434/api/tags` 应返回 4 个模型。
   不通就 `Start-ScheduledTask -TaskName OllamaService`。
2. 返回模型列表为空 = Ollama "失明"（踩坑#4）：启动时没拿到 `OLLAMA_MODELS`。
   必须带 `set OLLAMA_MODELS=D:\02_AI\models\Ollama\models` 再启动（自启任务已固化这点）。

---

# 第二部分 · 开发约定（要改代码时看这里）

## 最高纲领

**先读 `docs/架构宪法_第一性原理.md`**——它定义整个系统怎么构筑：公理→定理→组合，
三条铁律，以及"按稳定性决定自己做还是用现成"的首要判据。任何改动服从它。

## 接手先读（别边探边拼）

`docs/变更记录.md`（改动流水账，最新状态）→ `docs/踩坑记录.md`（已知坑）→
`docs/架构宪法_第一性原理.md` → `docs/数据契约.md`。别走到哪读到哪、靠猜（教训见踩坑#14）。

## 验证自主性

有 Windows MCP，可直接在用户机器跑验证，**无需每次停下来问**：
- 自主做：只读/验证类命令、A/B 对比、单篇验证、读脚本读数据 → 跑完直接报结果。
- 先问用户：全库重抽（154篇×API，花钱）、覆盖/删除数据、影响 Zotero 库的写操作、
  方向性抉择（改 schema、换技术路线——这是用户的领域判断）。
- 原则：可还原零成本的自己跑；有副作用/花钱/不可逆的先说清代价再问。

## 日志纪律（每次改动都要）

- 技术发现/踩坑 → 当场追加 `docs/踩坑记录.md`（编号+现象/根因/解法）
- 改代码/删数据/运维 → 当场记 `docs/变更记录.md`
- 需要改架构但还没做 → 记 `docs/待办与需求.md`
- 写中文用 Python `io.open(...encoding='utf-8')` 追加，避开 PowerShell 的 GBK 乱码
- **每个改动 Git commit**（项目已用 Git 管理，可回溯）

## 已知环境坑

- PowerShell 控制台中文乱码：显示问题非数据问题，用 Read 工具读文件确认真实内容。
- **MCP 调用约 60 秒超时**：长任务（精读、全库抽取、大模型读图）会超时但后台继续，
  用"发起后轮询文件结果"，别干等。
- 一切外部 API 先用真实数据实测（最重要的一条）。

## 模型分工（别搞混）

- 向量化：embedding 模型 `bge-m3`（本地免费，只做文本→向量）
- 结构化抽取：`deepseek-v4-pro`（输出少用pro更准，几乎不增成本）
- 精读：`deepseek-v4-flash`（输出9000字长文，用flash省钱）
- 图表数字化：**云端大模型必须**（硅基流动 Qwen3.5-397B/3.6-27B）；本地7B会编假数据（踩坑）
- 原则：**输出少的活上 pro，输出多的上 flash**

## 其他文档

`docs/架构总览.md`（数据流）· `docs/演进规划与模块地图.md`（模块索引+路线）·
`docs/对标报告_我们的思路 vs 前沿.md` · `docs/积木采购清单_可借鉴的开源积木.md` ·
`docs/正文数据关联_方向说明.md` · `docs/视觉模型选择_参考.md` · `docs/待办与需求.md`
