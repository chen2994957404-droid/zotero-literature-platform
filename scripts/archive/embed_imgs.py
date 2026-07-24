# -*- coding: utf-8 -*-
"""把 HTML 里的 <img src="images/xxx.jpg"> 替换成 base64 内嵌，生成自包含单文件。"""
import re, base64, os, sys
html_path = sys.argv[1]
base_dir  = sys.argv[2]   # images 所在的根目录
out_path  = sys.argv[3]

html = open(html_path, encoding='utf-8').read()

def embed(m):
    rel = m.group(1)
    fp = os.path.join(base_dir, rel)
    if not os.path.exists(fp):
        return m.group(0)
    ext = os.path.splitext(fp)[1].lstrip('.').lower()
    mime = 'jpeg' if ext in ('jpg','jpeg') else ext
    with open(fp,'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    return f'src="data:image/{mime};base64,{b64}"'

html = re.sub(r'src="(images/[^"]+)"', embed, html)
# 顺手清理开头多余的 "# 文献精读"
html = html.replace('<p># 文献精读</p>', '')
open(out_path,'w',encoding='utf-8').write(html)
print("WROTE", out_path, round(len(html)/1024), "KB")
