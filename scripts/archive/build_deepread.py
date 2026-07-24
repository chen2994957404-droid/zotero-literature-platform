# -*- coding: utf-8 -*-
"""图文精读版生成器：MineRU markdown -> DeepSeek 按高分子学人范式重组 -> HTML"""
import urllib.request, json, re, sys, os

MD_PATH = sys.argv[1]
IMG_DIR = sys.argv[2]        # images 目录（供HTML引用）
OUT_HTML = sys.argv[3]
DEEPSEEK_KEY = sys.argv[4]

md = open(MD_PATH, encoding='utf-8').read()

# 保护图片标记：换成占位符，避免 DeepSeek 改写图片文件名
imgs = re.findall(r'!\[\]\((images/[^)]+)\)', md)
for i, path in enumerate(imgs):
    md = md.replace(f'![]({path})', f'[[IMG{i}]]', 1)

if len(md) > 45000:
    md = md[:45000]

SYSTEM = """你是"高分子学人"公众号的资深科研文献编译编辑。请把给定的英文文献（已含图片占位符 [[IMG0]] [[IMG1]]...）编译成一篇**信息极其详尽、不缩水**的中文文献精读。宁可长，不可省。严格遵循以下固定范式（用 markdown，## 为栏目标题）：

## 导读
开篇一段：以"近期，某某等开发/报道了……"起笔，热情概述本文做了什么、核心亮点、关键数据、发表期刊与通讯作者，句末可用 🎉。

## 引言
两到三段，整合研究背景、领域应用、现有方法的三类主流思路及其缺陷、本文动机与体系设计。写成流畅充实的中文，保留专业细节。

## 实验
必须**分三部分详列，不可笼统**：
（1）实验药品：**逐一列出**原文出现的所有单体、引发剂、溶剂/离子液体、拓展体系试剂、荧光探针等，给全中文名+英文缩写。
（2）实验步骤：用 🌿 开头**分步骤**详列完整制备流程（每步一个 🌿），像菜谱一样可复现。
（3）测试表征：逐项列出所有表征手段（GPC、NMR、CLSM、MD、DFT、DSC、流变、拉伸等）及各自用途。
然后插入一个 **Question：各组分的作用是？** 用 🍁 开头**分点详答**每个关键组分的作用。

## 讨论
这是主体。按原文图表顺序，**每张图先放图片占位符，紧接着写"▲ 图X 标题：……"再逐个子图（图Xa、图Xb、图Xc……）分别详解**，说清每个子图展示了什么、关键数据、得出的结论。信息不缩水，保留所有数值（尺寸、模量、断裂能、应变%等）。全部图讲完后，插入一个 **Question：本论文材料为何性能优异？** 用 ☘️ 开头分点详答。

## 总结
以"总之，本文首次提出……"起笔，一大段升华：区别于传统方法的创新点、策略优势、普适性、机理完整性、开辟的新范式。

## 文献信息
英文标题、作者、通讯作者、期刊全称、DOI。

【硬性要求】
- 图片占位符 [[IMGn]] 必须原样保留、一个不少、放在其对应内容处，不得改写文件名。
- 逐子图解读是重点，不要把整张图笼统带过。
- 保留全部关键数据与专业术语，是"整理+翻译+扩写详解"，绝不是精简摘要。"""

body = json.dumps({
    "model": "deepseek-v4-pro",
    "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": md}
    ],
    "temperature": 0.3,
    "max_tokens": 8000
}, ensure_ascii=False)

req = urllib.request.Request("https://api.deepseek.com/chat/completions",
    data=body.encode('utf-8'), method="POST",
    headers={"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"})
resp = urllib.request.urlopen(req, timeout=300)
result = json.loads(resp.read())
content = result['choices'][0]['message']['content']
print("USAGE:", result.get('usage'))

# 把占位符还原成 HTML img 标签（相对路径引用 images 目录）
def repl_img(m):
    idx = int(m.group(1))
    if idx < len(imgs):
        return f'\n<img src="{imgs[idx]}" alt="figure {idx}">\n'
    return ''
content = re.sub(r'\[\[IMG(\d+)\]\]', repl_img, content)

# markdown 极简转 HTML
def md_to_html(t):
    lines = t.split('\n')
    out = []
    for ln in lines:
        s = ln.strip()
        if s.startswith('<img'):
            out.append(s); continue
        if s.startswith('## '):
            out.append(f'<h2 class="section">{s[3:].strip()}</h2>'); continue
        if s.startswith('### '):
            out.append(f'<h3>{s[4:].strip()}</h3>'); continue
        s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
        if s:
            out.append(f'<p>{s}</p>')
    return '\n'.join(out)

html_body = md_to_html(content)

HTML = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>文献精读</title>
<style>
body{{max-width:820px;margin:0 auto;padding:24px;font-family:-apple-system,"Microsoft YaHei",sans-serif;line-height:1.85;color:#222;background:#fafafa;}}
h2.section{{background:linear-gradient(90deg,#7b9cf0,#a78bde);color:#fff;padding:8px 20px;border-radius:20px;display:inline-block;font-size:19px;margin:34px 0 16px;}}
h3{{color:#5a6ec0;font-size:16px;margin-top:22px;}}
p{{margin:12px 0;text-align:justify;}}
img{{max-width:100%;display:block;margin:18px auto;border:1px solid #eee;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,.06);}}
strong{{color:#c0392b;}}
p:has(+ img), strong:only-child{{}}
</style></head>
<body>
{html_body}
</body></html>"""

open(OUT_HTML, 'w', encoding='utf-8').write(HTML)
print("WROTE", OUT_HTML, len(HTML), "bytes")
