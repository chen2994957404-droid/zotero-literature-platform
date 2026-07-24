# Zotero 文献精读闭环 · 使用说明

> 在 Zotero 里给文献打一个标签，系统自动生成图文精读并把笔记写回 Zotero。全程无需手动上传。

## 日常怎么用（超简单）

1. **确保两个程序开着**：
   - Zotero 桌面程序（数据源，必须开）
   - `启动Zotero闭环.bat`（精读引擎，双击启动，开机会自动起）
2. **在 Zotero 里给想精读的文献打上标签 `待精读`**（选中文献 → 右侧标签栏 → 加 `待精读`）
3. **等几分钟**，系统自动完成：
   - 拉取该文献的 PDF
   - MineRU 解析 + 裁完整图
   - DeepSeek 生成图文精读
   - 把精读笔记写回该文献（Zotero 同步后可见）
   - 标签自动从 `待精读` 变成 `已精读`
4. **看结果**：
   - **Zotero 里**：该文献下多一条"📖 图文精读"笔记（纯文字版，同步后可见）
   - **含图完整版**：`workflow_data/summary/` 目录里的 `<标题>_<key>_精读.html`（图文对照，浏览器打开）

## 完整链路

```
Zotero 打「待精读」标签
   ↓ (zotero_watcher.py 每60秒检测一次)
本地API读文献 → 定位本地PDF (storage/<附件key>/)
   ↓
MineRU 解析 (mineru_parse.py) → layout.json + 图 + 坐标
   ↓
精读生成 (deepread_v4.py) → 按坐标裁完整Figure + DeepSeek翻译重组 → HTML
   ↓
Web API 回写笔记 + 标签改「已精读」
```

## 为什么这么设计

- **本地 API 读、Web API 写**：Zotero 7 本地 API 只读（读文献、定位PDF快又稳），写操作走云端 Web API（回写笔记、改标签）。
- **标签驱动**：用 `待精读`/`已精读` 标签做状态机，处理过的不会重复处理（也避免 API 限流）。
- **裁图鲁棒**：按 layout.json 坐标从原PDF裁完整Figure，不依赖MineRU可能失败的碎图/题注识别，对不同期刊都通用。

## 常见问题

- **笔记没出现？** Zotero Web API 写的是云端，需要 Zotero **同步**后才在本地界面显示。可在 Zotero 里手动点同步。
- **想重新精读某篇？** 把它的 `已精读` 标签删掉，重新打 `待精读`。
- **精读质量/风格调整**：改 `scripts/_sys_prompt_v2.txt`。
- **限流(429)**：轮询已设为60秒一次，正常不会触发。若手动批量操作触发，等几分钟即可。

## ⚠️ 密钥安全（重要）

以下 key 明文存在 `启动Zotero闭环.bat` 和相关脚本里，**强烈建议全部重新生成**：
- DeepSeek API key
- MineRU token
- Zotero Web API key（zotero.org/settings/keys）
- n8n API key

调试过程中这些 key 都出现在了记录里。轮换后更新到 `启动Zotero闭环.bat` 顶部即可。

## 两套服务的关系

你现在有两个入口，按需用：
- **Zotero 闭环**（`启动Zotero闭环.bat`）：从 Zotero 打标签触发，最省事，推荐日常用。
- **n8n 表单**（http://localhost:5678/form/deepread-upload-001）：手动上传 PDF，适合处理不在 Zotero 里的文献。
