# -*- coding: utf-8 -*-
"""图文精读版 n8n 工作流：上传PDF -> MineRU -> DeepSeek精读 -> 图片内嵌HTML -> 写盘。
全部用 n8n 原生节点，不依赖容器内 Python。"""
import json, urllib.request, sys

N8N = "http://localhost:5678/api/v1"
N8N_KEY, MINERU_TOKEN, DEEPSEEK_KEY = sys.argv[1], sys.argv[2], sys.argv[3]

# 精读版 system prompt（与已验证脚本一致）
SYS = ("你是\"高分子学人\"公众号的资深科研文献编译编辑。请把给定英文文献（含图片占位符 [[IMG0]] [[IMG1]]...）"
"编译成信息极其详尽、不缩水的中文文献精读，宁长勿省。用 markdown，## 为栏目标题，严格按此范式：\\n"
"## 导读\\n开篇一段：以\"近期，某某等报道了……\"起笔，热情概述工作、亮点、关键数据、期刊与通讯作者，可用🎉。\\n"
"## 引言\\n2-3段：研究背景、领域应用、现有方法三类主流思路及缺陷、本文动机与体系设计。\\n"
"## 实验\\n分三部分详列：（1）实验药品：逐一列出所有单体/引发剂/溶剂/离子液体/拓展试剂/探针，给中文名+英文缩写。"
"（2）实验步骤：用🌿开头分步骤详列完整制备流程。（3）测试表征：逐项列出所有手段及用途。"
"然后插入 **Question：各组分的作用是？** 用🍁开头分点详答。\\n"
"## 讨论\\n主体。按图表顺序，每张图先放占位符，紧接\"▲ 图X 标题：……\"再逐子图（图Xa、图Xb…）分别详解，"
"说清展示内容、关键数据、结论，保留所有数值。全部图讲完后插入 **Question：本论文材料为何性能优异？** 用☘️开头分点详答。\\n"
"## 总结\\n以\"总之，本文首次提出……\"起笔升华：创新点、优势、普适性、机理、新范式。\\n"
"## 文献信息\\n英文标题、作者、通讯作者、期刊全称、DOI。\\n"
"硬性要求：图片占位符 [[IMGn]] 必须原样保留、一个不少、放在对应内容处；逐子图解读是重点；保留全部数据与术语。")

def node(name, ntype, tv, pos, params, extra=None):
    n={"parameters":params,"name":name,"type":ntype,"typeVersion":tv,"position":pos}
    if extra: n.update(extra)
    return n

nodes=[]
nodes.append(node("上传PDF","n8n-nodes-base.formTrigger",2.2,[-1600,0],{
    "formTitle":"文献图文精读","formDescription":"上传PDF，生成高分子学人风格的图文精读HTML",
    "formFields":{"values":[{"fieldLabel":"文档","fieldType":"file","requiredField":True}]},"options":{}},
    {"webhookId":"deepread-upload-001"}))
nodes.append(node("设置Token","n8n-nodes-base.set",3.4,[-1380,0],{
    "includeOtherFields":True,"assignments":{"assignments":[
        {"id":"t1","name":"mineru_token","type":"string","value":MINERU_TOKEN},
        {"id":"t2","name":"deepseek_key","type":"string","value":DEEPSEEK_KEY},
        {"id":"t3","name":"provider","type":"string","value":"deepseek"},
        {"id":"t4","name":"deepseek_model","type":"string","value":"deepseek-v4-pro"},
        {"id":"t5","name":"ollama_model","type":"string","value":"qwen3:8b"},
        {"id":"t6","name":"ollama_url","type":"string","value":"http://host.docker.internal:11434/v1/chat/completions"}]},"options":{}}))
nodes.append(node("提取文件信息","n8n-nodes-base.code",2,[-1160,0],{"jsCode":
"const bk=Object.keys(items[0].binary||{});\n"
"if(!bk.length) throw new Error('未检测到上传文件');\n"
"const key=bk[0];const fileName=items[0].binary[key].fileName||'document.pdf';\n"
"return [{json:{fileName,dataId:'file_'+Date.now(),binaryKey:key},binary:items[0].binary}];"}))
nodes.append(node("申请上传地址","n8n-nodes-base.httpRequest",4.2,[-940,0],{
    "method":"POST","url":"https://mineru.net/api/v4/file-urls/batch","sendHeaders":True,
    "headerParameters":{"parameters":[{"name":"Content-Type","value":"application/json"},
        {"name":"Authorization","value":"={{ 'Bearer ' + $('设置Token').first().json.mineru_token }}"}]},
    "sendBody":True,"specifyBody":"json",
    "jsonBody":"={\n \"enable_formula\": true,\n \"enable_table\": true,\n \"language\": \"en\",\n \"model_version\": \"vlm\",\n \"files\": [{\"name\": \"{{ $json.fileName }}\", \"is_ocr\": true, \"data_id\": \"{{ $json.dataId }}\"}]\n}","options":{}}))
nodes.append(node("解析上传地址","n8n-nodes-base.code",2,[-720,0],{"jsCode":
"const d=items[0].json.data||{};\n"
"const uploadUrl=(d.file_urls&&d.file_urls[0]);const batchId=d.batch_id;\n"
"if(!uploadUrl||!batchId) throw new Error('申请上传地址失败: '+JSON.stringify(items[0].json));\n"
"const prev=$('提取文件信息').first();\n"
"return [{json:{uploadUrl,batchId,fileName:prev.json.fileName},binary:prev.binary}];"}))
nodes.append(node("上传文件","n8n-nodes-base.httpRequest",4.2,[-500,0],{
    "method":"PUT","url":"={{ $json.uploadUrl }}",
    "sendHeaders":True,"headerParameters":{"parameters":[{"name":"Content-Type","value":""}]},
    "sendBody":True,"contentType":"binaryData","inputDataFieldName":"={{ Object.keys($binary)[0] }}","options":{}}))
nodes.append(node("等待10秒","n8n-nodes-base.wait",1.1,[-280,0],{"amount":10},{"webhookId":"deepread-wait-001"}))
nodes.append(node("查询解析结果","n8n-nodes-base.httpRequest",4.2,[-60,0],{
    "url":"={{ 'https://mineru.net/api/v4/extract-results/batch/' + $('解析上传地址').first().json.batchId }}",
    "sendHeaders":True,"headerParameters":{"parameters":[
        {"name":"Authorization","value":"={{ 'Bearer ' + $('设置Token').first().json.mineru_token }}"}]},"options":{}}))
nodes.append(node("是否done?","n8n-nodes-base.if",2.2,[160,0],{
    "conditions":{"options":{"caseSensitive":True,"typeValidation":"loose","version":2},
    "conditions":[{"leftValue":"={{ $json.data.extract_result[0].state }}","rightValue":"done",
    "operator":{"type":"string","operation":"equals"}}],"combinator":"and"},"options":{}}))
nodes.append(node("是否failed?","n8n-nodes-base.if",2.2,[160,220],{
    "conditions":{"options":{"caseSensitive":True,"typeValidation":"loose","version":2},
    "conditions":[{"leftValue":"={{ $json.data.extract_result[0].state }}","rightValue":"failed",
    "operator":{"type":"string","operation":"equals"}}],"combinator":"and"},"options":{}}))
nodes.append(node("解析失败","n8n-nodes-base.code",2,[380,320],{"jsCode":
"throw new Error('MineRU解析失败: '+(items[0].json.data.extract_result[0].err_msg||'未知'));"}))
nodes.append(node("等5秒重试","n8n-nodes-base.wait",1.1,[380,140],{"amount":5},{"webhookId":"deepread-wait-002"}))
nodes.append(node("下载结果zip","n8n-nodes-base.httpRequest",4.2,[380,-60],{
    "url":"={{ $json.data.extract_result[0].full_zip_url }}",
    "options":{"response":{"response":{"responseFormat":"file"}}}}))
nodes.append(node("解压","n8n-nodes-base.compression",1.1,[600,-60],{
    "operation":"decompress","binaryPropertyName":"data","outputPrefix":"file"}))

# 落地：把解压出的所有文件写到 /data/to_process/<id>/，再写 .ready 标记
# 守护脚本(watcher.py)监听该目录，接手裁图+精读
nodes.append(node("落地到to_process","n8n-nodes-base.code",2,[820,-60],{"jsCode":
"const fs=require('fs'); const path=require('path');\n"
"const bin=items[0].binary||{};\n"
"const fileName=($('提取文件信息').first().json.fileName||'doc').replace(/\\.[^.]+$/,'');\n"
"const taskId=fileName.replace(/[^a-zA-Z0-9_\\-]/g,'_').slice(0,60)+'_'+Date.now();\n"
"const base='/data/to_process/'+taskId;\n"
"const imgDir=base+'/images';\n"
"fs.mkdirSync(imgDir,{recursive:true});\n"
"// 写所有解压出的文件\n"
"for(const k of Object.keys(bin)){\n"
"  const fn=bin[k].fileName||k;\n"
"  const buff=await this.helpers.getBinaryDataBuffer(0,k);\n"
"  const low=fn.toLowerCase();\n"
"  let dest;\n"
"  if(/\\.(jpg|jpeg|png)$/i.test(low)) dest=path.join(imgDir,path.basename(fn));\n"
"  else dest=path.join(base,path.basename(fn));\n"
"  fs.writeFileSync(dest,buff);\n"
"}\n"
"// 保存原始文件名，供守护脚本命名输出\n"
"fs.writeFileSync(base+'/_origname.txt',fileName,'utf-8');\n"
"// 写 ready 标记（最后写，确保前面都写完）\n"
"fs.writeFileSync(base+'/.ready','1');\n"
"return [{json:{taskId, base, fileName, status:'已提交精读队列，稍后在 summary 目录查看结果'}}];"}))

def C(to): return {"node":to,"type":"main","index":0}
connections={
 "上传PDF":{"main":[[C("设置Token")]]},
 "设置Token":{"main":[[C("提取文件信息")]]},
 "提取文件信息":{"main":[[C("申请上传地址")]]},
 "申请上传地址":{"main":[[C("解析上传地址")]]},
 "解析上传地址":{"main":[[C("上传文件")]]},
 "上传文件":{"main":[[C("等待10秒")]]},
 "等待10秒":{"main":[[C("查询解析结果")]]},
 "查询解析结果":{"main":[[C("是否done?")]]},
 "是否done?":{"main":[[C("下载结果zip")],[C("是否failed?")]]},
 "是否failed?":{"main":[[C("解析失败")],[C("等5秒重试")]]},
 "等5秒重试":{"main":[[C("查询解析结果")]]},
 "下载结果zip":{"main":[[C("解压")]]},
 "解压":{"main":[[C("落地到to_process")]]},
}

wf={"name":"文献图文精读流","nodes":nodes,"connections":connections,"settings":{"executionOrder":"v1"}}
H={"X-N8N-API-KEY":N8N_KEY,"Content-Type":"application/json"}
# 删旧同名
try:
    lr=urllib.request.urlopen(urllib.request.Request(N8N+"/workflows?limit=100",headers=H))
    for w in json.loads(lr.read()).get("data",[]):
        if w.get("name")=="文献图文精读流":
            urllib.request.urlopen(urllib.request.Request(N8N+"/workflows/"+w["id"],method="DELETE",headers=H))
            print("deleted old",w["id"])
except Exception as e: print("cleanup:",e)
data=json.dumps(wf,ensure_ascii=False).encode('utf-8')
try:
    resp=urllib.request.urlopen(urllib.request.Request(N8N+"/workflows",data=data,method="POST",headers=H),timeout=30)
    r=json.loads(resp.read()); wid=r.get("id"); print("CREATED",wid)
    urllib.request.urlopen(urllib.request.Request(N8N+"/workflows/"+wid+"/activate",data=b"{}",method="POST",headers=H))
    print("ACTIVATED")
except urllib.error.HTTPError as e:
    print("HTTP",e.code,e.read().decode('utf-8'))
