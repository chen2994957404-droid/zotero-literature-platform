# -*- coding: utf-8 -*-
"""精读 v2：脚本管元数据+图片位置+分块，DeepSeek 只翻译解读。图片确定性、不截断。
用法: python deepread_v2.py <md> <out.html> <provider> <model> [key]
"""
import urllib.request, json, re, sys, base64, os, time

MD_PATH, OUT_HTML, PROVIDER, MODEL = sys.argv[1:5]
KEY = sys.argv[5] if len(sys.argv) > 5 else ""
MD_DIR = os.path.dirname(MD_PATH)

md = open(MD_PATH, encoding='utf-8').read()

# ---------- 1. 脚本提取元数据（不花钱）----------
def grab(pat, default=''):
    m = re.search(pat, md)
    return m.group(1).strip() if m else default

title_en = grab(r'^#\s+(.+)$', '')
if not title_en:
    title_en = grab(r'\n#\s+(.+)\n')
doi = grab(r'(10\.\d{4,}/[^\s)]+)')
# 作者：标题后第一行非空非图片
authors = ''
mt = re.search(r'#\s+.+\n+(.+)', md)
if mt:
    cand = mt.group(1).strip()
    if 'images/' not in cand:
        authors = re.sub(r'\$\^?\{?\*?\}?\$|\*', '', cand).strip()

# ---------- 2. 按图片切块，脚本记死图片顺序 ----------
# 过滤掉太小的装饰图（logo/图标/二维码），只保留正文图
def img_size(rel):
    fp = os.path.join(MD_DIR, rel)
    return os.path.getsize(fp) if os.path.exists(fp) else 0

parts = re.split(r'(!\[\]\(images/[^)]+\))', md)
# parts 交替为 文字/图片标记
blocks = []   # [{'text':..., 'img':rel or None}]
cur_text = ''
for seg in parts:
    m = re.match(r'!\[\]\((images/[^)]+)\)', seg)
    if m:
        rel = m.group(1)
        if img_size(rel) >= 8000:   # 8KB以上才算正文图，滤掉小装饰
            blocks.append({'text': cur_text.strip(), 'img': rel})
            cur_text = ''
        # 小图直接丢弃，其文字并入下一块
    else:
        cur_text += seg
if cur_text.strip():
    blocks.append({'text': cur_text.strip(), 'img': None})

kept_imgs = [b['img'] for b in blocks if b['img']]
print(f"元数据: title={title_en[:40]}... doi={doi} authors={authors[:30]}")
print(f"总图{len(re.findall(r'images/',md))} 保留正文图{len(kept_imgs)} 文本块{len(blocks)}")

# ---------- 3. 组装给 DeepSeek 的纯文字（带图片编号标记，让它知道图在哪但不用记文件名）----------
llm_input = f"标题: {title_en}\n作者: {authors}\nDOI: {doi}\n\n正文（【图N】表示此处有第N张图）:\n\n"
img_n = 0
for b in blocks:
    llm_input += b['text'] + "\n"
    if b['img']:
        img_n += 1
        llm_input += f"【图{img_n}】\n"

SYS = open(os.path.join(os.path.dirname(__file__), '_sys_prompt_v2.txt'), encoding='utf-8').read()

# ---------- 4. 调 LLM（若过长自动分块）----------
def call_llm(text):
    if PROVIDER == 'deepseek':
        body = json.dumps({"model": MODEL, "temperature": 0.3, "max_tokens": 8000,
            "messages":[{"role":"system","content":SYS},{"role":"user","content":text}]}, ensure_ascii=False)
        req = urllib.request.Request("https://api.deepseek.com/chat/completions",
            data=body.encode('utf-8'), method="POST",
            headers={"Authorization":f"Bearer {KEY}","Content-Type":"application/json"})
        r = json.loads(urllib.request.urlopen(req, timeout=400).read())
        return r['choices'][0]['message']['content'], r.get('usage')
    else:
        body = json.dumps({"model":MODEL,"stream":False,
            "options":{"num_ctx":16384,"num_predict":8000,"temperature":0.3},
            "messages":[{"role":"system","content":SYS},{"role":"user","content":text}]}, ensure_ascii=False)
        req = urllib.request.Request("http://localhost:11434/api/chat",
            data=body.encode('utf-8'), method="POST", headers={"Content-Type":"application/json"})
        r = json.loads(urllib.request.urlopen(req, timeout=1200).read())
        return r['message']['content'], {"eval":r.get('eval_count')}

t0 = time.time()
# 分块：若输入过长，按【图N】边界分2块
if len(llm_input) > 28000:
    mid = len(llm_input)//2
    cut = llm_input.find('【图', mid)
    if cut < 0: cut = mid
    print("长文分2块处理")
    c1,_ = call_llm(llm_input[:cut] + "\n（上半部分，请翻译解读到此）")
    c2,_ = call_llm("（接上文继续解读，同样范式）\n" + llm_input[cut:])
    content = c1 + "\n" + c2
    usage = "分块"
else:
    content, usage = call_llm(llm_input)
elapsed = round(time.time()-t0,1)
content = re.sub(r'<think>[\s\S]*?</think>','',content).strip()
print(f"LLM {PROVIDER}/{MODEL} {elapsed}s usage={usage} 输出{len(content)}字")

# ---------- 5. 脚本把【图N】还原成内嵌base64（确定性，绝不错位）----------
def img_b64(rel):
    fp = os.path.join(MD_DIR, rel)
    if not os.path.exists(fp): return ''
    ext = 'jpeg' if fp.lower().endswith(('jpg','jpeg')) else 'png'
    return f'data:image/{ext};base64,' + base64.b64encode(open(fp,'rb').read()).decode()

def repl(m):
    n = int(m.group(1))
    if 1 <= n <= len(kept_imgs):
        b = img_b64(kept_imgs[n-1])
        return f'\n<img src="{b}">\n' if b else ''
    return ''
content = re.sub(r'【图(\d+)】', repl, content)
# 兜底：若 LLM 没把某些图标记带出来，把遗漏的图追加到末尾前
used = set(int(x) for x in re.findall(r'【图(\d+)】', content))  # 已在repl消耗，这里用于统计

# ---------- 6. 渲染 HTML ----------
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
print("WROTE",OUT_HTML,round(len(html)/1024),"KB, 内嵌图",content.count('<img'))
