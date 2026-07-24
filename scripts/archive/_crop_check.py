# -*- coding: utf-8 -*-
import json, os, re, fitz
base = 'workflow_data/mineru_output'
lay = json.load(open(base+'/layout.json', encoding='utf-8'))
pdf = [f for f in os.listdir(base) if f.endswith('origin.pdf')][0]
doc = fitz.open(base+'/'+pdf)

def bt(blk):
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

fig_map = {}
for pg in lay['pdf_info']:
    pidx = pg['page_idx']
    fignum = None
    for blk in pg.get('para_blocks', []):
        m = re.match(r'\s*Figure\s*(\d+)', bt(blk))
        if m:
            fignum = int(m.group(1))
            break
    if fignum is None:
        continue
    xs0 = []; ys0 = []; xs1 = []; ys1 = []
    for blk in pg.get('para_blocks', []):
        if blk.get('type') in ('image', 'chart', 'table'):
            bx = blk['bbox']
            if (bx[2]-bx[0])*(bx[3]-bx[1]) < 2000:
                continue
            xs0.append(bx[0]); ys0.append(bx[1]); xs1.append(bx[2]); ys1.append(bx[3])
    if not xs0:
        continue
    fig_map[fignum] = {'page': pidx, 'bbox': [min(xs0), min(ys0), max(xs1), max(ys1)], 'psize': pg['page_size']}

print('Figure numbers:', sorted(fig_map.keys()))
for fn in sorted(fig_map.keys()):
    it = fig_map[fn]
    page = doc[it['page']]
    sx = page.rect.width/it['psize'][0]
    sy = page.rect.height/it['psize'][1]
    bx = it['bbox']
    r = fitz.Rect(max(0, bx[0]*sx-3), max(0, bx[1]*sy-3), min(page.rect.width, bx[2]*sx+3), min(page.rect.height, bx[3]*sy+3))
    pix = page.get_pixmap(clip=r, matrix=fitz.Matrix(2, 2))
    pix.save('workflow_data/summary/_fig%d.png' % fn)
    print('Figure%d p%d %dx%d' % (fn, it['page'], pix.width, pix.height))
