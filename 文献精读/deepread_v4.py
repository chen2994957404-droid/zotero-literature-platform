# -*- coding: utf-8 -*-
"""精读 v4：用 layout.json 的 page_size 精确裁完整Figure（通用所有文献）+ 脚本管元数据/图位置 + LLM只翻译解读。
用法: python deepread_v4.py <mineru_output_dir> <out.html> <provider> <model> [key]
（2026-08-11 框架化：流水线移入 main()，参数走 modules/cli，行为不变）
"""
import os, sys, re, json, base64, time, fitz

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from modules.cli import pos
from modules.llm_client import chat as _chat   # LLM 调用走公理件（精读输出重，用 flash 省钱由上游 MODEL 决定）

MIN_OK = 3000   # 精读正文低于这个字数就是废品，不许静默写盘


def main():
    MO_DIR, OUT_HTML, PROVIDER, MODEL = pos(0), pos(1), pos(2), pos(3)
    KEY = pos(4) or ""

    # 解析结果不全时要报清楚缺什么。原来直接取 [0]，缺文件就抛裸 IndexError，
    # 调用方（watcher）只能把「list index out of range」写进日志，看不出是 MineRU 没出全。
    def pick(suffix, what):
        try:
            names = sorted(f for f in os.listdir(MO_DIR) if f.endswith(suffix))
        except OSError as e:
            raise SystemExit(f'读不到解析目录 {MO_DIR}：{e}')
        if not names:
            raise SystemExit(f'解析结果不完整：{MO_DIR} 里没有{what}（*{suffix}）'
                             f'—— 多半是 MineRU 解析失败或没解析完，删掉该目录重跑即可')
        return names[0]

    mdf = pick('.md', 'Markdown 正文')
    layf = os.path.join(MO_DIR, 'layout.json')
    if not os.path.exists(layf):
        raise SystemExit(f'解析结果不完整：{MO_DIR} 里没有 layout.json（版面数据）'
                         f'—— 多半是 MineRU 解析失败或没解析完，删掉该目录重跑即可')
    pdff = pick('origin.pdf', '原始 PDF')

    md = open(os.path.join(MO_DIR, mdf), encoding='utf-8').read()
    lay = json.load(open(layf, encoding='utf-8'))
    doc = fitz.open(os.path.join(MO_DIR, pdff))

    # ---------- 1. 元数据 ----------
    def grab(pat, d=''):
        m = re.search(pat, md, re.M); return m.group(1).strip() if m else d
    title_en = grab(r'^#\s+(.+)$'); doi = grab(r'(10\.\d{4,}/[^\s)]+)')
    authors = ''
    mt = re.search(r'#\s+.+\n+(.+)', md)
    if mt and 'images/' not in mt.group(1):
        authors = re.sub(r'\$\^?\{?\*?\}?\$|\*', '', mt.group(1)).strip()

    # ---------- 2. 按"Figure N 题注"归组，同页多块合并成完整 Figure ----------
    def block_text(blk):
        t = ''
        for sub in (blk.get('blocks') or []):
            for ln in sub.get('lines', []):
                for sp in ln.get('spans', []): t += sp.get('content', '')
        if not t:
            for ln in blk.get('lines', []):
                for sp in ln.get('spans', []): t += sp.get('content', '')
        return t

    # 鲁棒策略：遍历每页，把视觉块(image/chart/table)按纵向聚类成 Figure。
    # 题注(Figure N)能识别就用作caption；识别不了按出现顺序自动编号。不再强依赖题注，避免丢图。
    def find_caption(pg):
        for blk in pg.get('para_blocks', []):
            txt = block_text(blk)
            m = re.match(r'\s*(?:Figure|Fig\.?|图)\s*(\d+)', txt)
            if m: return txt[:150]
            for sub in (blk.get('blocks') or []):
                if sub.get('type') == 'image_caption':
                    ct = ''.join(sp.get('content', '') for ln in sub.get('lines', []) for sp in ln.get('spans', []))
                    if re.match(r'\s*(?:Figure|Fig\.?|图)\s*\d', ct): return ct[:150]
        return ''

    raw_figs = []  # 每项: {page, bbox, caption, psize, ytop}
    for pg in lay['pdf_info']:
        pidx = pg['page_idx']
        vis = []
        for blk in pg.get('para_blocks', []):
            if blk.get('type') in ('image', 'chart', 'table'):
                bx = blk['bbox']; area = (bx[2]-bx[0])*(bx[3]-bx[1])
                if area < 2500: continue  # 滤小图标/残块
                vis.append(bx)
        if not vis: continue
        # 纵向聚类：按y排序，间隔过大(>页高15%)则拆成不同Figure
        vis.sort(key=lambda b: b[1])
        ph = pg['page_size'][1]; gap = ph*0.15
        groups = [[vis[0]]]
        for b in vis[1:]:
            if b[1]-groups[-1][-1][3] > gap: groups.append([b])
            else: groups[-1].append(b)
        cap = find_caption(pg)
        for gi, g in enumerate(groups):
            xs0 = [b[0] for b in g]; ys0 = [b[1] for b in g]; xs1 = [b[2] for b in g]; ys1 = [b[3] for b in g]
            merged = [min(xs0), min(ys0), max(xs1), max(ys1)]
            # 面积过小的整组也跳过（避免零碎）
            if (merged[2]-merged[0])*(merged[3]-merged[1]) < 8000: continue
            raw_figs.append({'page': pidx, 'bbox': merged,
                'caption': cap if gi == 0 else '', 'psize': pg['page_size']})

    # 按出现顺序编号
    fig_map = {i+1: raw_figs[i] for i in range(len(raw_figs))}

    figs = []
    for fn in sorted(fig_map.keys()):
        it = fig_map[fn]; page = doc[it['page']]
        sx = page.rect.width/it['psize'][0]; sy = page.rect.height/it['psize'][1]
        bx = it['bbox']
        r = fitz.Rect(max(0, bx[0]*sx-3), max(0, bx[1]*sy-3),
                      min(page.rect.width, bx[2]*sx+3), min(page.rect.height, bx[3]*sy+3))
        pix = page.get_pixmap(clip=r, matrix=fitz.Matrix(3, 3))
        b64 = 'data:image/png;base64,' + base64.b64encode(pix.tobytes('png')).decode()
        figs.append({'b64': b64, 'caption': it['caption'], 'page': it['page'], 'num': fn})
    print(f"元数据 title={title_en[:35]} doi={doi}")
    print(f"识别Figure编号 {sorted(fig_map.keys())}，裁出 {len(figs)} 张完整图")

    # ---------- 3. LLM 输入 ----------
    body_txt = re.sub(r'!\[\]\(images/[^)]+\)', '', md)
    llm_input = f"标题: {title_en}\n作者: {authors}\nDOI: {doi}\n\n本文共有 {len(figs)} 张图，题注：\n"
    for i, fg in enumerate(figs, 1):
        llm_input += f"【图{i}】{fg['caption'][:120]}\n"
    llm_input += "\n请在讨论部分按顺序用【图N】标记每张图插入位置。\n\n正文:\n" + body_txt
    # V4 上下文 1M token，正文（约 3~6 万字符）完全放得下，不必粗暴截断。
    # 留 15 万字符上限只为防解析异常产出的巨型垃圾文本。
    if len(llm_input) > 150000: llm_input = llm_input[:150000]

    SYS = open(os.path.join(os.path.dirname(__file__), '_sys_prompt_v2.txt'), encoding='utf-8').read()

    def call_llm(text, max_tokens=32000, thinking=False):
        return _chat(SYS, text, provider=PROVIDER, model=MODEL, key=KEY,
                     temperature=0.3, max_tokens=max_tokens, thinking=thinking)

    t0 = time.time()
    content = ''
    # 两次尝试：先关思考+3.2万额度（快且省）；不够则开思考+6.4万额度（更强）
    for attempt, (mt, think) in enumerate([(32000, False), (64000, True)], 1):
        try:
            content = re.sub(r'<think>[\s\S]*?</think>', '', call_llm(llm_input, mt, think)).strip()
        except Exception as e:
            print(f"  第{attempt}次调用失败: {e}"); content = ''
        if len(content) >= MIN_OK:
            break
        print(f"  第{attempt}次输出仅 {len(content)} 字（<{MIN_OK}），重试更大额度…")
    print(f"LLM {round(time.time()-t0,1)}s 输出{len(content)}字")
    if len(content) < MIN_OK:
        # 宁可不产出，也不产出「只有图没有字」的废品精读（否则会被标成已精读、不再重跑）
        sys.exit(f"[FAIL] LLM 正文仅 {len(content)} 字，判定失败，不写盘。请检查模型/额度。")

    # ---------- 4. 确定性插图 ----------
    used = set()
    def repl(m):
        n = int(m.group(1)); used.add(n)
        return f'\n<img src="{figs[n-1]["b64"]}">\n' if 1 <= n <= len(figs) else ''
    content = re.sub(r'【图(\d+)】', repl, content)
    missing = [i for i in range(1, len(figs)+1) if i not in used]
    if missing:
        add = ''.join(f'\n<img src="{figs[i-1]["b64"]}">\n' for i in missing)
        content = content.replace('## 总结', '（补充图）'+add+'\n## 总结', 1) if '## 总结' in content else content+add

    # ---------- 5. 渲染 ----------
    out = []
    for ln in content.split('\n'):
        s = ln.strip()
        if s.startswith('<img'): out.append(s); continue
        if s.startswith('## '): out.append(f'<h2 class="section">{s[3:].strip()}</h2>'); continue
        if s.startswith('### '): out.append(f'<h3>{s[4:].strip()}</h3>'); continue
        s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
        if s: out.append(f'<p>{s}</p>')
    css = 'body{max-width:820px;margin:0 auto;padding:24px;font-family:-apple-system,"Microsoft YaHei",sans-serif;line-height:1.85;color:#222;background:#fafafa}h2.section{background:linear-gradient(90deg,#7b9cf0,#a78bde);color:#fff;padding:8px 20px;border-radius:20px;display:inline-block;font-size:19px;margin:34px 0 16px}h3{color:#5a6ec0;font-size:16px;margin-top:22px}p{margin:12px 0;text-align:justify}img{max-width:100%;display:block;margin:18px auto;border:1px solid #eee;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,.06)}strong{color:#c0392b}'
    html = f'<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>文献精读</title><style>{css}</style></head><body>' + '\n'.join(out) + '</body></html>'
    open(OUT_HTML, 'w', encoding='utf-8').write(html)
    print("WROTE", OUT_HTML, round(len(html)/1024), "KB 插图", content.count('<img'))


if __name__ == '__main__':
    main()
