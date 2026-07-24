# -*- coding: utf-8 -*-
"""生成全新的文献解析+总结合并工作流，并通过 n8n API 创建。"""
import json, urllib.request, sys

N8N = "http://localhost:5678/api/v1"
N8N_KEY = sys.argv[1]
MINERU_TOKEN = sys.argv[2]
DEEPSEEK_KEY = sys.argv[3]

SUMMARY_SYS = (
    "你是科研文献助手。请用中文为给定英文文献生成结构化总结，包含以下小标题："
    "## 研究背景与问题、## 核心方法、## 主要发现、## 创新点、## 意义与局限。"
    "内容准确、有信息量，使用 markdown。"
)

def node(name, ntype, tv, pos, params, extra=None):
    n = {"parameters": params, "name": name, "type": ntype,
         "typeVersion": tv, "position": pos}
    if extra: n.update(extra)
    return n

nodes = []

# 1 表单触发
nodes.append(node("上传PDF", "n8n-nodes-base.formTrigger", 2.2, [-1600,0], {
    "formTitle":"文献解析总结","formDescription":"上传PDF，自动解析并生成中文总结",
    "formFields":{"values":[{"fieldLabel":"文档","fieldType":"file","requiredField":True}]},
    "options":{}}, {"webhookId":"lit-upload-001"}))

# 2 提取文件信息
nodes.append(node("提取文件信息","n8n-nodes-base.code",2,[-1380,0],{"jsCode":
"const bk=Object.keys(items[0].binary||{});\n"
"if(!bk.length) throw new Error('未检测到上传文件');\n"
"const key=bk[0];\n"
"const fileName=items[0].binary[key].fileName||'document.pdf';\n"
"return [{json:{fileName,dataId:'file_'+Date.now(),binaryKey:key},binary:items[0].binary}];"}))

# token 设置节点
nodes.append(node("设置Token","n8n-nodes-base.set",3.4,[-1380,0],{
    "includeOtherFields":True,
    "assignments":{"assignments":[
        {"id":"t1","name":"mineru_token","type":"string","value":MINERU_TOKEN},
        {"id":"t2","name":"deepseek_key","type":"string","value":DEEPSEEK_KEY}]},
    "options":{}}))

# 3 申请上传地址
nodes.append(node("申请上传地址","n8n-nodes-base.httpRequest",4.2,[-1160,0],{
    "method":"POST","url":"https://mineru.net/api/v4/file-urls/batch",
    "sendHeaders":True,"headerParameters":{"parameters":[
        {"name":"Content-Type","value":"application/json"},
        {"name":"Authorization","value":"={{ 'Bearer ' + $('设置Token').first().json.mineru_token }}"}]},
    "sendBody":True,"specifyBody":"json",
    "jsonBody":"={\n \"enable_formula\": true,\n \"enable_table\": true,\n \"language\": \"en\",\n \"model_version\": \"vlm\",\n \"files\": [{\"name\": \"{{ $json.fileName }}\", \"is_ocr\": true, \"data_id\": \"{{ $json.dataId }}\"}]\n}",
    "options":{}}))

# 4 解析上传地址
nodes.append(node("解析上传地址","n8n-nodes-base.code",2,[-940,0],{"jsCode":
"const d=items[0].json.data||{};\n"
"const uploadUrl=(d.file_urls&&d.file_urls[0]);\n"
"const batchId=d.batch_id;\n"
"if(!uploadUrl||!batchId) throw new Error('申请上传地址失败: '+JSON.stringify(items[0].json));\n"
"const prev=$('提取文件信息').first();\n"
"return [{json:{uploadUrl,batchId,fileName:prev.json.fileName},binary:prev.binary}];"}))

# 5 PUT 上传（无Authorization头）
nodes.append(node("上传文件","n8n-nodes-base.httpRequest",4.2,[-720,0],{
    "method":"PUT","url":"={{ $json.uploadUrl }}",
    "sendHeaders":True,"headerParameters":{"parameters":[{"name":"Content-Type","value":""}]},
    "sendBody":True,"contentType":"binaryData","inputDataFieldName":"={{ Object.keys($binary)[0] }}",
    "options":{}}))

# 6 等待
nodes.append(node("等待10秒","n8n-nodes-base.wait",1.1,[-500,0],{"amount":10},{"webhookId":"lit-wait-001"}))

# 7 轮询结果
nodes.append(node("查询解析结果","n8n-nodes-base.httpRequest",4.2,[-280,0],{
    "url":"={{ 'https://mineru.net/api/v4/extract-results/batch/' + $('解析上传地址').first().json.batchId }}",
    "sendHeaders":True,"headerParameters":{"parameters":[
        {"name":"Authorization","value":"={{ 'Bearer ' + $('设置Token').first().json.mineru_token }}"}]},
    "options":{}}))

# 8 是否完成
nodes.append(node("是否done?","n8n-nodes-base.if",2.2,[-60,0],{
    "conditions":{"options":{"caseSensitive":True,"typeValidation":"loose","version":2},
    "conditions":[{"leftValue":"={{ $json.data.extract_result[0].state }}","rightValue":"done",
    "operator":{"type":"string","operation":"equals"}}],"combinator":"and"},"options":{}}))

# 9 是否失败
nodes.append(node("是否failed?","n8n-nodes-base.if",2.2,[-60,220],{
    "conditions":{"options":{"caseSensitive":True,"typeValidation":"loose","version":2},
    "conditions":[{"leftValue":"={{ $json.data.extract_result[0].state }}","rightValue":"failed",
    "operator":{"type":"string","operation":"equals"}}],"combinator":"and"},"options":{}}))

# 10 抛错
nodes.append(node("解析失败","n8n-nodes-base.code",2,[160,320],{"jsCode":
"throw new Error('MineRU解析失败: '+(items[0].json.data.extract_result[0].err_msg||'未知'));"}))

# 11 等5秒再查
nodes.append(node("等5秒重试","n8n-nodes-base.wait",1.1,[160,140],{"amount":5},{"webhookId":"lit-wait-002"}))

# 12 下载zip
nodes.append(node("下载结果zip","n8n-nodes-base.httpRequest",4.2,[160,-60],{
    "url":"={{ $json.data.extract_result[0].full_zip_url }}",
    "options":{"response":{"response":{"responseFormat":"file"}}}}))

# 13 解压
nodes.append(node("解压","n8n-nodes-base.compression",1.1,[380,-60],{
    "operation":"decompress","binaryPropertyName":"data","outputPrefix":"file"}))

# 14 提取Markdown文本
nodes.append(node("提取Markdown","n8n-nodes-base.code",2,[600,-60],{"jsCode":
"const bin=items[0].binary||{};\n"
"let mdKey=null;\n"
"for(const k of Object.keys(bin)){ if((bin[k].fileName||'').toLowerCase().endsWith('.md')){mdKey=k;break;} }\n"
"if(!mdKey) throw new Error('未找到md文件, keys='+Object.keys(bin).join(','));\n"
"const buff=await this.helpers.getBinaryDataBuffer(0,mdKey);\n"
"let md=buff.toString('utf-8');\n"
"if(md.length>20000) md=md.slice(0,20000);\n"
"return [{json:{markdown:md}}];"}))

# 15 DeepSeek 总结
nodes.append(node("DeepSeek总结","n8n-nodes-base.httpRequest",4.2,[820,-60],{
    "method":"POST","url":"https://api.deepseek.com/chat/completions",
    "sendHeaders":True,"headerParameters":{"parameters":[
        {"name":"Content-Type","value":"application/json"},
        {"name":"Authorization","value":"={{ 'Bearer ' + $('设置Token').first().json.deepseek_key }}"}]},
    "sendBody":True,"specifyBody":"json",
    "jsonBody":"={{ JSON.stringify({model:'deepseek-v4-pro',messages:[{role:'system',content:"+json.dumps(SUMMARY_SYS,ensure_ascii=False)+"},{role:'user',content:$json.markdown}]}) }}",
    "options":{}}))

# 16 组装markdown
nodes.append(node("组装文档","n8n-nodes-base.code",2,[1040,-60],{"jsCode":
"const c=items[0].json.choices[0].message.content;\n"
"const fn=$('提取文件信息').first().json.fileName.replace(/\\.[^.]+$/,'');\n"
"return [{json:{fileName:fn,markdown:'# '+fn+'\\n\\n'+c}}];"}))

# 17 转文件
nodes.append(node("转为文件","n8n-nodes-base.convertToFile",1.1,[1260,-60],{
    "operation":"toText","sourceProperty":"markdown","options":{"fileName":"={{ $json.fileName }}.md"}}))

# 18 写盘
nodes.append(node("写入summary","n8n-nodes-base.readWriteFile",1.1,[1480,-60],{
    "operation":"write","fileName":"=/data/summary/{{ $('组装文档').first().json.fileName }}.md","options":{}}))

def C(frm,to,idx=0):
    return {"node":to,"type":"main","index":idx}

connections={
 "上传PDF":{"main":[[C(0,"设置Token")]]},
 "设置Token":{"main":[[C(0,"提取文件信息")]]},
 "提取文件信息":{"main":[[C(0,"申请上传地址")]]},
 "申请上传地址":{"main":[[C(0,"解析上传地址")]]},
 "解析上传地址":{"main":[[C(0,"上传文件")]]},
 "上传文件":{"main":[[C(0,"等待10秒")]]},
 "等待10秒":{"main":[[C(0,"查询解析结果")]]},
 "查询解析结果":{"main":[[C(0,"是否done?")]]},
 "是否done?":{"main":[[C(0,"下载结果zip")],[C(0,"是否failed?")]]},
 "是否failed?":{"main":[[C(0,"解析失败")],[C(0,"等5秒重试")]]},
 "等5秒重试":{"main":[[C(0,"查询解析结果")]]},
 "下载结果zip":{"main":[[C(0,"解压")]]},
 "解压":{"main":[[C(0,"提取Markdown")]]},
 "提取Markdown":{"main":[[C(0,"DeepSeek总结")]]},
 "DeepSeek总结":{"main":[[C(0,"组装文档")]]},
 "组装文档":{"main":[[C(0,"转为文件")]]},
 "转为文件":{"main":[[C(0,"写入summary")]]},
}

wf={"name":"文献解析总结-合并流","nodes":nodes,"connections":connections,
    "settings":{"executionOrder":"v1"}}

H={"X-N8N-API-KEY":N8N_KEY,"Content-Type":"application/json"}
# 删除旧的同名工作流
try:
    lr=urllib.request.urlopen(urllib.request.Request(N8N+"/workflows?limit=100",headers=H))
    for w in json.loads(lr.read()).get("data",[]):
        if w.get("name")=="文献解析总结-合并流":
            urllib.request.urlopen(urllib.request.Request(N8N+"/workflows/"+w["id"],method="DELETE",headers=H))
            print("deleted old",w["id"])
except Exception as e: print("cleanup:",e)

data=json.dumps(wf,ensure_ascii=False).encode('utf-8')
req=urllib.request.Request(N8N+"/workflows",data=data,method="POST",headers=H)
try:
    resp=urllib.request.urlopen(req,timeout=30)
    r=json.loads(resp.read())
    wid=r.get("id"); print("CREATED id=",wid)
    urllib.request.urlopen(urllib.request.Request(N8N+"/workflows/"+wid+"/activate",data=b"{}",method="POST",headers=H))
    print("ACTIVATED")
except urllib.error.HTTPError as e:
    print("HTTP",e.code,e.read().decode('utf-8'))
