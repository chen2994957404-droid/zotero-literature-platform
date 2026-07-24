# -*- coding: utf-8 -*-
"""精读 v3：按 MineRU bbox 从原PDF裁【完整Figure】(解决碎图) + 脚本管元数据/图片位置 + DeepSeek只翻译解读。
用法: python deepread_v3.py <mineru_output_dir> <out.html> <provider> <model> [key]
"""
import urllib.request, json, re, sys, base64, os, time, fitz

MO_DIR, OUT_HTML, PROVIDER, MODEL = sys.argv[1:5]
KEY = sys.argv[5] if len(sys.argv) > 5 else ""

# 定位文件
mdf = [f for f in os.listdir(MO_DIR) if f.endswith('full.md') or (f.endswith('.md') and 'full' in f)]
mdf = mdf[0] if mdf else 'full.md'
clf = [f for f in os.listdir(MO_DIR) if f.endswith('content_list.json')][0]
pdff = [f for f in os.listdir(MO_DIR) if f.endswith('origin.pdf')][0]

md = open(os.path.join(MO_DIR, mdf), encoding='utf-8').read()
clist = json.load(open(os.path.join(MO_DIR, clf), encoding='utf-8'))
doc = fitz.open(os.path.join(MO_DIR, pdff))

# ---------- 1. 元数据（脚本正则）----------
def grab(pat, d=''):
    m = re.search(pat, md, re.M); return m.group(1).strip() if m else d
title_en = grab(r'^#\s+(.+)$')
doi = grab(r'(10\.\d{4,}/[^\s)]+)')
authors = ''
mt = re.search(r'#\s+.+\n+(.+)', md)
if mt and 'images/' not in mt.group(1):
    authors = re.sub(r'\$\^?\{?\*?\}?\$|\*','',mt.group(1)).strip()

# ---------- 2. 从 content_list 取"有意义的图"，按 bbox 从PDF裁完整图 ----------
# 判定基准宽（MineRU坐标系）：取所有image bbox 的 max x2
img_items = [x for x in clist if x.get('type')=='image']
BASE_W = max((x['bbox'][2] for x in img_items), default=912)

def crop_fig(item, idx):
    page = doc[item['page_idx']]
    sx = page.rect.width / BASE_W
    bx = item['bbox']
    # 稍微外扩，避免切边
    r = fitz.Rect(max(0,bx[0]*sx-4), max(0,bx[1]*sx-4),
                  min(page.rect.width,bx[2]*sx+4), min(page.rect.height,bx[3]*sx+4))
    if r.width < 30 or r.height < 30: return None
    pix = page.get_pixmap(clip=r, matrix=fitz.Matrix(3,3))
    return 'data:image/png;base64,' + base64.b64encode(pix.tobytes('png')).decode()

# 只保留"够大"的图（滤掉logo/图标）：面积阈值
figs = []
for x in img_items:
    bx = x['bbox']
    area = (bx[2]-bx[0])*(bx[3]-bx[1])
    if area >= 6000:   # MineRU坐标下的面积阈值，滤小图标
        b64 = crop_fig(x, len(figs))
        if b64:
            cap = (x.get('image_caption') or [''])
            cap = cap[0] if cap else ''
            figs.append({'b64':b64,'caption':cap,'page':x['page_idx']})
print(f"元数据 title={title_en[:35]} doi={doi}")
print(f"content图{len(img_items)} 保留完整Figure{len(figs)}")

# ---------- 3. 组装LLM输入（正文文字 + 图caption，用【图N】标位）----------
# 从 md 取正文文字（去掉图片标记）
body_txt = re.sub(r'!\[\]\(images/[^)]+\)', '', md)
llm_input = f"标题: {title_en}\n作者: {authors}\nDOI: {doi}\n\n"
llm_input += "以下是文献正文。文中共有 %d 张图，其题注分别为：\n" % len(figs)
for i,fg in enumerate(figs,1):
    llm_input += f"【图{i}】{fg['caption'][:120]}\n"
llm_input += "\n请在讨论部分按顺序用【图N】标记每张图应插入的位置。\n\n正文:\n" + body_txt
if len(llm_input) > 40000:
    llm_input = llm_input[:40000]

SYS = open(os.path.join(os.path.dirname(__file__), '_sys_prompt_v2.txt'), encoding='utf-8').read()

# ---------- 4. 调 LLM ----------
def call_llm(text):
    if PROVIDER=='deepseek':
        body=json.dumps({"model":MODEL,"temperature":0.3,"max_tokens":8000,
            "messages":[{"role":"system","content":SYS},{"role":"user","content":text}]},ensure_ascii=False)
        req=urllib.request.Request("https://api.deepseek.com/chat/completions",data=body.encode(),
            method="POST",headers={"Authorization":f"Bearer {KEY}","Content-Type":"application/json"})
        r=json.loads(urllib.request.urlopen(req,timeout=400).read())
        return r['choices'][0]['message']['content']
    else:
        body=json.dumps({"model":MODEL,"stream":False,"options":{"num_ctx":16384,"num_predict":8000,"temperature":0.3},
            "messages":[{"role":"system","content":SYS},{"role":"user","content":text}]},ensure_ascii=False)
        req=urllib.request.Request("http://localhost:11434/api/chat",data=body.encode(),
            method="POST",headers={"Content-Type":"application/json"})
        r=json.loads(urllib.request.urlopen(req,timeout=1200).read())
        return r['message']['content']

t0=time.time()
content=call_llm(llm_input)
content=re.sub(r'<think>[\s\S]*?</think>','',content).strip()
print(f"LLM {elapsed if False else round(time.time()-t0,1)}s 输出{len(content)}字")

# ---------- 5. 脚本确定性插图：【图N】->完整Figure；遗漏的图补到讨论末尾 ----------
used=set()
def repl(m):
    n=int(m.group(1)); used.add(n)
    if 1<=n<=len(figs): return f'\n<img src="{figs[n-1]["b64"]}">\n'
    return ''
content=re.sub(r'【图(\d+)】',repl,content)
missing=[i for i in range(1,len(figs)+1) if i not in used]
if missing:
    add=''.join(f'\n<img src="{figs[i-1]["b64"]}">\n' for i in missing)
    # 追加到"总结"前，或直接末尾
    if '## 总结' in content: content=content.replace('## 总结','（补充图）'+add+'\n## 总结',1)
    else: content+=add

# ---------- 6. 渲染 ----------
out=[]
for ln in content.split('\n'):
    s=ln.strip()
    if s.startswith('<img'): out.append(s); continue
    if s.startswith('## '): out.append(f'<h2 class="section">{s[3:].strip()}</h2>'); continue
    if s.startswith('### '): out.append(f'<h3>{s[4:].strip()}</h3>'); continue
    s=re.sub(r'\*\*(.+?)\*\*',r'<strong>\1</strong>',s)
    if s: out.append(f'<p>{s}</p>')
css='body{max-width:820px;margin:0 auto;padding:24px;font-family:-apple-system,"Microsoft YaHei",sans-serif;line-height:1.85;color:#222;background:#fafafa}h2.section{background:linear-gradient(90deg,#7b9cf0,#a78bde);color:#fff;padding:8px 20px;border-radius:20px;display:inline-block;font-size:19px;margin:34px 0 16px}h3{color:#5a6ec0;font-size:16px;margin-top:22px}p{margin:12px 0;text-align:justify}img{max-width:100%;display:block;margin:18px auto;border:1px solid #eee;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,.06)}strong{color:#c0392b}'
html=f'<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>文献精读</title><style>{css}</style></head><body>'+'\n'.join(out)+'</body></html>'
open(OUT_HTML,'w',encoding='utf-8').write(html)
print("WROTE",OUT_HTML,round(len(html)/1024),"KB 插图",content.count('<img'))
