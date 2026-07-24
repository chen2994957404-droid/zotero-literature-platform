# 文献智能系统

围绕 Zotero 的文献工作流,两大能力:
- **精读(深度)**:给文献打标签 → 自动生成中文图文精读 → 作为附件挂回 Zotero
- **问答(广度)**:全库文献向量化 → 用大白话向整个文献库提问

## 快速开始

### 精读某篇文献
1. 确保 **Zotero 桌面**开着,`启动Zotero闭环.bat`运行中(开机自启)
2. 在 Zotero 里给文献打标签 `待精读`
3. 几分钟后:该文献下多一个 `summary` 附件(带图完整精读),标签变 `已精读`
4. **记得在 Zotero 点同步**,让附件同步到其他设备

### 向文献库提问
```
python scripts\ask.py "哪些文献用了氢键增韧？"
```
它从全库检索相关内容,用DeepSeek综合回答并附来源。

### 把新文献加入可搜索库
```
python scripts\vectorize_library.py     # 全库轻量向量化(增量,只处理新的)
```

## 文档索引

| 文档 | 内容 |
|------|------|
| `docs/架构总览.md` | 系统怎么运作、各部件关系、关键设计决策 |
| `docs/数据契约.md` | 数据怎么组织存放(换工具/维护的地基) |
| `docs/Zotero闭环使用说明.md` | 精读日常使用详解 |
| `docs/向量化问答说明.md` | 向量化和问答的使用与原理 |
| `docs/换设备重装指南.md` | 换新电脑时从零复现整套系统 |
| `docs/踩坑记录.md` | 一路遇到的所有问题+根因+解法 |
| `docs/API_verified.md` | 实测验证的 MineRU/DeepSeek API 规格 |

## 系统两条线

**精读线(深度)**:Zotero打标签 → MineRU解析 → 裁完整图 → DeepSeek精读 → summary附件回写Zotero。重、花钱,给精选文献。
**问答线(广度)**:Zotero全文API取文字 → 切块 → bge-m3向量化 → Chroma库 → 提问检索。轻、免费、占空间极小,给全库文献。

产物都按 `docs/数据契约.md` 规整存在 `workflow_data/library/` 和 `workflow_data/vector_db/`。

## 数据存储位置(都在D盘,不占C盘)

- 向量库:`workflow_data/vector_db/`(约几十MB,139篇才86MB)
- 精读/解析:`workflow_data/library/<文献key>/`
- 只有Zotero自己的数据库和Python包在C盘(固定不增长,不用管)

## ⚠️ 待办:轮换密钥

搭建中以下 key 明文出现在脚本里,建议全部重新生成后更新到 `启动Zotero闭环.bat`:
DeepSeek key、MineRU token、Zotero API key、n8n API key。

## 开机自启状态

- ✅ Docker Desktop → n8n 容器 `restart:always` 自动起
- ✅ Ollama(本地模型:bge-m3向量化 / qwen短任务)
- ✅ Zotero 闭环服务(`Zotero精读闭环.lnk`)
- ⬜ n8n 精读服务:改为手动(备用入口,需要时双击 `启动精读服务.bat`)

运行日志:`workflow_data/logs/`

## 长期维护提示

对话会有尽头,但文档是永久的。以后在新对话里,让助手先读 `docs/` 下的文档(尤其架构总览、数据契约、踩坑记录),几分钟就能接上全部上下文继续维护。
