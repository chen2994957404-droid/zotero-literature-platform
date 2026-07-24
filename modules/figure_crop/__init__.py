# -*- coding: utf-8 -*-
"""figure_crop · 裁图基础件（公理：解析结果 → 完整 Figure 图片）

职责：从 MineRU 解析结果（layout.json + 原PDF）按坐标裁出【完整 Figure】。
这是精读线独有、也最复杂的公理（踩坑 #7 花时间最多，智慧全固化在此）。

公理特征：只做「解析目录 → 图片列表」这一件事，不依赖上层。

对外接口：
  - crop_figures(parsed_dir) → list[{b64, caption, page, num}]
    b64 是可直接嵌 HTML 的 base64 PNG。

依赖：PyMuPDF(fitz)。需 parsed_dir 含 layout.json + *_origin.pdf。

固化的踩坑 #7（对所有期刊通用）：
  - 用坐标从原PDF裁完整图，不用 MineRU 碎图（子问题A）
  - 用 layout.json 的 page_size 做缩放基准，bbox 与 PDF 1:1（子问题B）
  - 合并 image/chart/table 三类视觉块（子问题C）
  - 纵向聚类成 Figure，不依赖题注，题注失败也不丢图（子问题D）
"""
import os, re, base64


def _block_text(blk):
    t = ''
    for sub in (blk.get('blocks') or []):
        for ln in sub.get('lines', []):
            for sp in ln.get('spans', []):
                t += sp.get('content', '')
    if not t:
        for ln in blk.get('lines', []):
            for sp in ln.get('spans', []):
                t += sp.get('content', '')
    return t


def _find_caption(pg):
    for blk in pg.get('para_blocks', []):
        txt = _block_text(blk)
        if re.match(r'\s*(?:Figure|Fig\.?|图)\s*(\d+)', txt):
            return txt[:150]
        for sub in (blk.get('blocks') or []):
            if sub.get('type') == 'image_caption':
                ct = ''.join(sp.get('content', '') for ln in sub.get('lines', [])
                             for sp in ln.get('spans', []))
                if re.match(r'\s*(?:Figure|Fig\.?|图)\s*\d', ct):
                    return ct[:150]
    return ''


def crop_figures(parsed_dir):
    """从解析目录裁出完整 Figure 列表。返回 [{b64, caption, page, num}, ...]。"""
    import json, fitz
    layf = os.path.join(parsed_dir, 'layout.json')
    pdffs = [f for f in os.listdir(parsed_dir) if f.endswith('origin.pdf')]
    if not os.path.exists(layf) or not pdffs:
        return []
    lay = json.load(open(layf, encoding='utf-8'))
    doc = fitz.open(os.path.join(parsed_dir, pdffs[0]))

    raw_figs = []
    for pg in lay['pdf_info']:
        pidx = pg['page_idx']
        vis = []
        for blk in pg.get('para_blocks', []):
            if blk.get('type') in ('image', 'chart', 'table'):
                bx = blk['bbox']
                if (bx[2]-bx[0])*(bx[3]-bx[1]) < 2500:   # 滤小图标
                    continue
                vis.append(bx)
        if not vis:
            continue
        vis.sort(key=lambda b: b[1])
        gap = pg['page_size'][1] * 0.15                  # 纵向间隔>页高15%则拆
        groups = [[vis[0]]]
        for b in vis[1:]:
            if b[1] - groups[-1][-1][3] > gap:
                groups.append([b])
            else:
                groups[-1].append(b)
        cap = _find_caption(pg)
        for gi, g in enumerate(groups):
            merged = [min(b[0] for b in g), min(b[1] for b in g),
                      max(b[2] for b in g), max(b[3] for b in g)]
            if (merged[2]-merged[0])*(merged[3]-merged[1]) < 8000:
                continue
            raw_figs.append({'page': pidx, 'bbox': merged,
                             'caption': cap if gi == 0 else '', 'psize': pg['page_size']})

    figs = []
    for i, it in enumerate(raw_figs, 1):
        page = doc[it['page']]
        sx = page.rect.width / it['psize'][0]
        sy = page.rect.height / it['psize'][1]
        bx = it['bbox']
        r = fitz.Rect(max(0, bx[0]*sx-3), max(0, bx[1]*sy-3),
                      min(page.rect.width, bx[2]*sx+3), min(page.rect.height, bx[3]*sy+3))
        pix = page.get_pixmap(clip=r, matrix=fitz.Matrix(3, 3))
        b64 = 'data:image/png;base64,' + base64.b64encode(pix.tobytes('png')).decode()
        figs.append({'b64': b64, 'caption': it['caption'], 'page': it['page'], 'num': i})
    return figs
