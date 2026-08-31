# -*- coding: utf-8 -*-
"""清理无 PDF 的残留条目：先列清单，人确认后再删。**两步分开是刻意的。**

分 A/B 两组，因为「能不能安全删」是两种完全不同的判断：
  A 组 = 重复残留（库里另有一条同标题/同 DOI 且带 PDF 的）→ 删掉不丢任何东西
  B 组 = 库里独一份（没找到带 PDF 的正版）→ **删了就真没了**，必须人确认

用法:
  python -m tools.curate.junk              列清单并导出（不删任何东西）
  python -m tools.curate.junk --删除        按上一步的清单删（危险，先看清单）
  python -m tools.curate.junk --删除 --只删A  只删确认是重复残留的那组
"""
import io
import json
import os
import re
import sys
import time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters import zotero_client as zotero
from shared.kernel import paths, role
from shared.kernel.cli import flag


def norm(t):
    return re.sub(r'[^a-z0-9]', '', (t or '').lower())


def fetch_tops():
    """取全部顶层条目（分页）。走适配层，红线 #5。"""
    tops = []
    start = 0
    while True:
        d = zotero.search_items(limit=100, start=start)
        if not d:
            break
        tops += d
        start += 100
        if len(d) < 100:
            break
    return tops


def split_junk(tops):
    """无附件的条目分成 A（重复残留）/ B（独一份）两组，返回 (A, B)。"""
    withpdf_titles, withpdf_dois = set(), set()
    for x in tops:
        if x['data'].get('itemType') == 'attachment':
            continue
        if x['meta'].get('numChildren', 0) > 0:
            withpdf_titles.add(norm(x['data'].get('title')))
            if x['data'].get('DOI'):
                withpdf_dois.add(x['data']['DOI'].lower())

    A, B = [], []
    for x in tops:
        d = x['data']
        if d.get('itemType') == 'attachment' or x['meta'].get('numChildren', 0) > 0:
            continue
        nt, doi = norm(d.get('title')), (d.get('DOI') or '').lower()
        (A if (nt and nt in withpdf_titles) or (doi and doi in withpdf_dois) else B).append(x)
    return A, B


def write_list(A, B):
    """把清单写成人能看的 txt + 机器能用的 json，返回 txt 路径。"""
    lines = ['=== A组：确认是重复残留（库里有带PDF的正版），可安全删 ===\n']
    lines += [f"[{x['key']}] {(x['data'].get('title') or '')[:75]}" for x in A]
    lines.append('\n\n=== B组：库里独一份（没找到带PDF正版），请你确认是否要删 ===\n')
    lines += [f"[{x['key']}] ({x['data'].get('itemType')}) {(x['data'].get('title') or '')[:70]}"
              for x in B]
    out = paths.junk_list('txt')
    io.open(out, 'w', encoding='utf-8').write('\n'.join(lines))
    io.open(paths.junk_list('json'), 'w', encoding='utf-8').write(json.dumps(
        {'A': [x['key'] for x in A], 'B': [x['key'] for x in B]}))
    return out


def do_list():
    """列清单，不动任何数据。"""
    A, B = split_junk(fetch_tops())
    out = write_list(A, B)
    print(f'A组 {len(A)} 个, B组 {len(B)} 个')
    print(f'清单已导出: {out}')
    print('确认后删除：python -m tools.curate.junk --删除')


def do_delete(only_a=False, forced=False):
    """按清单删除。**只删清单里的**，不重新扫库 —— 人确认的是那份清单。"""
    j = json.load(io.open(paths.junk_list('json'), encoding='utf-8'))
    keys = j['A'] + ([] if only_a else j['B'])
    print(f'待删 {len(keys)} 个条目' + ('（只删A组）' if only_a else ''))

    ok = fail = 0
    for i, k in enumerate(keys):
        # 删除走适配层：取版本、限流退避、「本来就不在了算成功」都在那里。
        # 适配层刻意把删除单独做成一个原语并写明边界 ——
        # **它只用于用户明确要删的条目，绝不用于「更新产物」**（踩坑 #28）。
        try:
            zotero.delete_item(k, action='删除垃圾条目', force=forced, log=print)
            ok += 1
        except Exception as e:
            fail += 1
            if fail <= 5:
                print(f'  失败 {k}: {e}')
        if (i + 1) % 15 == 0:
            print(f'  进度 {i+1}/{len(keys)} 成功{ok} 失败{fail}')
        time.sleep(0.3)
    print(f'\n完成：删除成功 {ok}，失败 {fail}')


def main():
    if not flag('--删除') and not flag('--delete'):
        do_list()
        return
    # 机器角色守卫：这件事只允许在运行端（主力机）做，见 docs/两台机器的分工.md
    forced = flag('--force')
    role.require_prod('删除 Zotero 条目', force=forced)
    do_delete(only_a=flag('--只删A'), forced=forced)


if __name__ == '__main__':
    main()
