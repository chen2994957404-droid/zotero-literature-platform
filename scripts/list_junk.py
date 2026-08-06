# -*- coding: utf-8 -*-
"""列出无PDF的条目，分A组(重复残留)/B组(独一份)，导出清单供确认。"""
import urllib.request, json, re, os

# 本机配置（Zotero 用户ID / 附件目录）统一从 modules.config 读，换电脑只改 .env
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
try:
    from modules.config import need_site as _site
except Exception:
    _site = lambda n: _os.environ.get(n) or (_ for _ in ()).throw(RuntimeError(f'缺少本机设置 {n}，请在控制面板或 .env 中配置'))
_UID = _site('ZOTERO_USER_ID')
_STORAGE = _site('ZOTERO_STORAGE')
base = f'http://localhost:23119/api/users/{_UID}'
h = {'Zotero-Allowed-Request': 'true'}
def get(p):
    return json.loads(urllib.request.urlopen(urllib.request.Request(base+p, headers=h), timeout=20).read())

tops = []; s = 0
while True:
    d = get(f'/items/top?limit=100&start={s}')
    if not d: break
    tops += d; s += 100
    if len(d) < 100: break

def norm(t): return re.sub(r'[^a-z0-9]', '', (t or '').lower())

withpdf_titles = set(); withpdf_dois = set()
for x in tops:
    if x['data'].get('itemType') == 'attachment': continue
    if x['meta'].get('numChildren', 0) > 0:
        withpdf_titles.add(norm(x['data'].get('title')))
        if x['data'].get('DOI'): withpdf_dois.add(x['data'].get('DOI').lower())

noatt = [x for x in tops if x['data'].get('itemType') != 'attachment' and x['meta'].get('numChildren', 0) == 0]
A = []; B = []
for x in noatt:
    d = x['data']; nt = norm(d.get('title')); doi = (d.get('DOI') or '').lower()
    if (nt and nt in withpdf_titles) or (doi and doi in withpdf_dois):
        A.append(x)
    else:
        B.append(x)

lines = []
lines.append('=== A组：确认是重复残留（库里有带PDF的正版），可安全删 ===\n')
for x in A:
    lines.append(f"[{x['key']}] {(x['data'].get('title') or '')[:75]}")
lines.append('\n\n=== B组：库里独一份（没找到带PDF正版），请你确认是否要删 ===\n')
for x in B:
    lines.append(f"[{x['key']}] ({x['data'].get('itemType')}) {(x['data'].get('title') or '')[:70]}")

out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'workflow_data', '待删条目清单.txt')
open(out, 'w', encoding='utf-8').write('\n'.join(lines))
# 同时保存key列表供删除脚本用
json.dump({'A': [x['key'] for x in A], 'B': [x['key'] for x in B]},
          open(out.replace('.txt', '.json'), 'w', encoding='utf-8'))
print(f'A组 {len(A)} 个, B组 {len(B)} 个')
print(f'清单已导出: {out}')
