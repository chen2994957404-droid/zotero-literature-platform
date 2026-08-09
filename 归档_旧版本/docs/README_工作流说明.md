# 文献解析总结工作流 — 使用说明

> 由 Claude 重建并实测跑通（2026-07-22）。原 GPT 版因 MineRU API 字段猜错、总结流输入写死而无法运行，已推翻重做。

## 现在能做什么

上传一篇 PDF 文献 → 自动用 MineRU 解析成 Markdown → DeepSeek 生成中文结构化总结 → 写入 `workflow_data/summary/<文件名>.md`。

**已验证**：用你那篇 JACS 论文完整跑通，输出高质量中文总结（见 summary 目录）。

## 怎么用

1. 确认 n8n 容器在跑：`docker ps`（容器名 n8n-literature，端口 5678）
2. 打开工作流的表单地址：**http://localhost:5678/form/lit-upload-001**
3. 上传 PDF，等约 60–90 秒
4. 总结出现在 `workflow_data/summary/` 目录

工作流名：**文献解析总结-合并流**（当前 id `xEXhFbqJm3O4Uq9G`，已激活）

## 工作流结构（17 节点一条链）

上传PDF → 设置Token → 提取文件信息 → 申请上传地址(MineRU) → 解析上传地址 →
上传文件(PUT) → 等待10秒 → 查询解析结果 → 是否done? →
  ├ done → 下载zip → 解压 → 提取Markdown → DeepSeek总结 → 组装文档 → 转为文件 → 写入summary
  └ 否 → 是否failed? → (是)抛错 / (否)等5秒重试 → 回到查询解析结果

## 相对 GPT 版修复的关键点

1. MineRU 无 task_id 层：删掉 GPT 发明的「按batch_id查task_id」「提取task_id」两个错节点
2. 轮询用 `GET /extract-results/batch/{batch_id}`，状态字段是 `data.extract_result[0].state`（GPT 写的 `data.state` 是错的）
3. PUT 上传阿里云 OSS 时**不能带 Content-Type 头**，否则签名不匹配（已置空修复）
4. 总结流不再写死问题，改为读取真实解析出的 Markdown
5. 「设置Token」节点接入主链（原来是孤立的，导致引用失败）

## 怎么调总结风格

打开「DeepSeek总结」节点，改 system 提示词那一段即可（现在是"研究背景/方法/发现/创新点/意义局限"五段式）。改一句话的事。想换模型可把 `deepseek-v4-pro` 改成 `deepseek-v4-flash`（更快更便宜）。

## ⚠️ 安全：请轮换这些密钥

以下密钥在调试中出现在了对话/代码里，建议全部重新生成：
- **n8n API key**（Settings → n8n API）
- **MineRU token**（mineru.net 账户）
- **DeepSeek key**（platform.deepseek.com）

目前这三个 key 明文存在「设置Token」节点里。更安全的做法是改用 n8n 的 Credentials（HTTP Header Auth 类型），我可以帮你迁移。

## 相关文件
- `build_workflow.py` — 生成工作流的脚本（改节点后重跑即可更新）
- `API_verified.md` — 实测验证的 MineRU / DeepSeek 真实 API 规格
- `wf_backup/` — 原三个旧工作流的备份
