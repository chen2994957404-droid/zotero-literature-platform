# -*- coding: utf-8 -*-
"""通用精读生成器：支持 deepseek 或 ollama(本地) 任意模型。
用法: python deepread_any.py <md> <imgdir> <out.html> <provider> <model> [deepseek_key]
provider: deepseek | ollama
"""
import urllib.request, json, re, sys, base64, os, time

MD_PATH, IMG_DIR, OUT_HTML, PROVIDER, MODEL = sys.argv[1:6]
KEY = sys.argv[6] if len(sys.argv) > 6 else ""

md = open(MD_PATH, encoding='utf-8').read()
imgs = re.findall(r'!\[\]\((images/[^)]+)\)', md)
for i, p in enumerate(imgs):
    md = md.replace(f'![]({p})', f'[[IMG{i}]]', 1)
if len(md) > 45000:
    md = md[:45000]

SYS = open(os.path.join(os.path.dirname(__file__), '_sys_prompt.txt'), encoding='utf-8').read()

t0 = time.time()
if PROVIDER == 'deepseek':
    body = json.dumps({"model": MODEL, "temperature": 0.3, "max_tokens": 8000,
        "messages": [{"role":"system","content":SYS},{"role":"user","content":md}]}, ensure_ascii=False)
    req = urllib.request.Request("https://api.deepseek.com/chat/completions",
        data=body.encode('utf-8'), method="POST",
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    result = json.loads(urllib.request.urlopen(req, timeout=400).read())
    content = result['choices'][0]['message']['content']
    usage = result.get('usage')
else:  # ollama
    body = json.dumps({"model": MODEL, "stream": False,
        "options": {"num_ctx": 16384, "num_predict": 8000, "temperature": 0.3},
        "messages": [{"role":"system","content":SYS},{"role":"user","content":md}]}, ensure_ascii=False)
    req = urllib.request.Request("http://localhost:11434/api/chat",
        data=body.encode('utf-8'), method="POST", headers={"Content-Type":"application/json"})
    result = json.loads(urllib.request.urlopen(req, timeout=1200).read())
    content = result['message']['content']
    usage = {"eval_count": result.get('eval_count'), "prompt_eval_count": result.get('prompt_eval_count')}

elapsed = round(time.time() - t0, 1)
# 去掉 deepseek-r1 的 <think> 段
content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
print(f"PROVIDER={PROVIDER} MODEL={MODEL} TIME={elapsed}s USAGE={usage} LEN={len(content)}")

def embed(m):
    idx = int(m.group(1))
    if idx < len(imgs):
        fp = os.path.join(IMG_DIR, imgs[idx].split('/',1)[1]) if IMG_DIR else None
    return ''
# 还原图片为内嵌 base64
def repl(m):
    idx = int(m.group(1))
    if idx >= len(imgs): return ''
    rel = imgs[idx]  # images/xxx.jpg
    fp = os.path.join(os.path.dirname(MD_PATH), rel)
    if not os.path.exists(fp): return ''
    ext = 'jpeg' if fp.lower().endswith(('jpg','jpeg')) else 'png'
    b64 = base64.b64encode(open(fp,'rb').read()).decode()
    return f'\n<img src="data:image/{ext};base64,{b64}">\n'
content = re.sub(r'\[\[IMG(\d+)\]\]', repl, content)

out = []
for ln in content.split('\n'):
    s = ln.strip()
    if s.startswith('<img'): out.append(s); continue
    if s.startswith('## '): out.append(f'<h2 class="section">{s[3:].strip()}</h2>'); continue
    if s.startswith('### '): out.append(f'<h3>{s[4:].strip()}</h3>'); continue
    s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
    if s: out.append(f'<p>{s}</p>')
css='body{max-width:820px;margin:0 auto;padding:24px;font-family:-apple-system,"Microsoft YaHei",sans-serif;line-height:1.85;color:#222;background:#fafafa}h2.section{background:linear-gradient(90deg,#7b9cf0,#a78bde);color:#fff;padding:8px 20px;border-radius:20px;display:inline-block;font-size:19px;margin:34px 0 16px}h3{color:#5a6ec0;font-size:16px;margin-top:22px}p{margin:12px 0;text-align:justify}img{max-width:100%;display:block;margin:18px auto;border:1px solid #eee;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,.06)}strong{color:#c0392b}'
banner=f'<div style="background:#eef;padding:6px 14px;border-radius:8px;font-size:13px;color:#558">本文由 {PROVIDER}/{MODEL} 生成，耗时 {elapsed}s</div>'
html=f'<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>文献精读</title><style>{css}</style></head><body>{banner}'+'\n'.join(out)+'</body></html>'
open(OUT_HTML,'w',encoding='utf-8').write(html)
print("WROTE", OUT_HTML, round(len(html)/1024), "KB")
