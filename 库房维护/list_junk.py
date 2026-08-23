# -*- coding: utf-8 -*-
"""列出无PDF的条目，分A组(重复残留)/B组(独一份)，导出清单供确认。"""
import urllib.request, json, re, os, sys

# 【标准开头】项目根加入 import 路径 + 强制 UTF-8 输出（详见 docs/代码规范_标准脚本模板.md）
_ROOT = os.path.dirname(os.path.abspath(__file__))
while True:
    if os.path.isdir(os.path.join(_ROOT, 'modules')):
        break                      # 项目根特征：modules/ 目录只在根存在
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        break                      # 到盘符根，兜底
    _ROOT = parent
sys.path.insert(0, _ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from modules.config import need_site

# 本机配置（Zotero 用户ID / 附件目录）统一从 modules.config 读，换电脑只改 .env
_UID = need_site('ZOTERO_USER_ID')
_STORAGE = need_site('ZOTERO_STORAGE')
base = f'http://localhost:23119/api/users/{_UID}'
h = {'Zotero-Allowed-Request': 'true'}


def get(p):
    return json.loads(urllib.request.urlopen(urllib.request.Request(base+p, headers=h), timeout=20).read())


def norm(t):
    return re.sub(r'[^a-z0-9]', '', (t or '').lower())


def main():
    tops = []; s = 0
    while True:
        d = get(f'/items/top?limit=100&start={s}')
        if not d: break
        tops += d; s += 100
        if len(d) < 100: break

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

    out = os.path.join(_ROOT, 'workflow_data', '待删条目清单.txt')
    open(out, 'w', encoding='utf-8').write('\n'.join(lines))
    # 同时保存key列表供删除脚本用
    json.dump({'A': [x['key'] for x in A], 'B': [x['key'] for x in B]},
              open(out.replace('.txt', '.json'), 'w', encoding='utf-8'))
    print(f'A组 {len(A)} 个, B组 {len(B)} 个')
    print(f'清单已导出: {out}')


if __name__ == '__main__':
    main()
