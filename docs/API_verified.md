# 已实测验证的 API 规格（2026-07-22）

## MineRU（PDF → Markdown）
Base: https://mineru.net/api/v4
Auth: `Authorization: Bearer <token>`

### 1. 申请上传地址
POST /file-urls/batch
Body:
```json
{"enable_formula":true,"enable_table":true,"language":"en","model_version":"vlm",
 "files":[{"name":"paper.pdf","is_ocr":true,"data_id":"xxx"}]}
```
真实返回：`data.batch_id`, `data.file_urls[0]`（预签名 URL，短时有效，需立刻上传）

### 2. 上传文件
PUT <file_urls[0]>   —— 直接 PUT 二进制，**不要带 Authorization 头**，Content-Type 可省。返回 200。

### 3. 轮询结果（无 task_id 层！GPT 版的节点7/8/9 是错的）
GET /extract-results/batch/{batch_id}
Auth: Bearer token
真实返回：`data.extract_result[0]` = { data_id, file_name, state(running/done/failed), err_msg, full_zip_url }

### 4. 下载结果
GET <full_zip_url> → zip，内含 full.md + images/。

## DeepSeek（总结）
POST https://api.deepseek.com/chat/completions
Auth: Bearer <key>
模型：`deepseek-v4-pro`（存在，已验证）/ `deepseek-v4-flash`
标准 OpenAI 格式：messages[{role,content}]，返回 choices[0].message.content
一篇论文总结约 2700 输入 + 900 输出 tokens，成本极低。

## 关键修正点（相对 GPT 版）
1. 删除节点 7「按batch_id查询task_id」、节点8「提取task_id」——不存在这一层
2. 节点9 轮询改为 GET /extract-results/batch/{batch_id}
3. state 字段路径：data.extract_result[0].state（不是 data.state）
4. full_zip_url 路径：data.extract_result[0].full_zip_url
5. 总结流输入改为读取解析出的 full.md（不再写死问题）
