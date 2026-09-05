# -*- coding: utf-8 -*-
"""取全文的命令行入口（只解析参数，一行业务逻辑都没有）。

用法:
    python -m tools.getpdf --probe                       # 浏览器在不在（先跑这个）
    python -m tools.getpdf 10.1016/j.cej.2025.164092     # 取一篇
    python -m tools.getpdf 10.1016/xxx 10.1002/yyy       # 取几篇
    python -m tools.getpdf --file dois.txt               # 从文件读，一行一个
    python -m tools.getpdf --file dois.txt --gap 30      # 每篇之间等 30 秒
    python -m tools.getpdf --file dois.txt --limit 10    # 这次最多取 10 篇
    python -m tools.getpdf 10.1016/xxx --out D:/somewhere

**跑之前**：那台机器上要有一个带调试口启动的浏览器，**里面得有人过过一次人机验证**
（机构订阅靠出口 IP 自动生效，不用登录；人机验证的通行证跟着浏览器的用户资料走）。
专开一个就行，别跟日常那个抢 —— 双击 `launch/取全文用的浏览器.bat`，或者：

    msedge  --remote-debugging-port=9333 --user-data-dir=<给它单独一个文件夹>
    chrome  --remote-debugging-port=9333 --user-data-dir=<给它单独一个文件夹>

默认很慢（每篇间隔 20 秒、单次最多 25 篇），这是**故意的**：
出版商封的是整个机构的 IP，代价全校担。要快请自己显式加 --gap / --limit。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import io

from shared.adapters import pdf_fetch
from shared.kernel.cli import flag, opt, positionals, wants_help
from tools import getpdf


def _read_file(path):
    """一行一个 DOI，`#` 开头是注释。"""
    with io.open(path, encoding='utf-8', errors='replace') as fh:
        return [ln.strip() for ln in fh
                if ln.strip() and not ln.strip().startswith('#')]


def main():
    if wants_help():
        print(__doc__)
        return 0

    if flag('--probe'):
        p = getpdf.probe()
        if p['ok']:
            print(f'浏览器连得上：{p["cdp"]}（当前开着 {p.get("pages", 0)} 个标签页）')
            return 0
        print(f'浏览器连不上：{p["cdp"]}')
        print(f'  原因：{p.get("error", "")}')
        print('  它需要带调试口启动，专门开一个就行（双击 launch/取全文用的浏览器.bat）：')
        print('    msedge --remote-debugging-port=9333')
        return 1

    dois = list(positionals())
    src = opt('--file')
    if src:
        if not os.path.isfile(src):
            print(f'找不到这个文件：{src}')
            return 2
        dois += _read_file(src)
    if not dois:
        print(__doc__)
        return 2

    bad = [d for d in dois if not pdf_fetch.is_doi(d)]
    if bad:
        print(f'这些看着不像 DOI，已跳过：{", ".join(bad[:5])}'
              + ('…' if len(bad) > 5 else ''))

    where = opt('--out') or getpdf.out_dir(create=True)
    gap = int(opt('--gap') or getpdf.GAP)
    limit = int(opt('--limit') or getpdf.LIMIT)

    p = getpdf.probe()
    if not p['ok']:
        print(f'浏览器连不上（{p["cdp"]}），先跑 --probe 看怎么办。')
        return 1

    print(f'要取 {min(len([d for d in dois if pdf_fetch.is_doi(d)]), limit)} 篇，'
          f'每篇间隔 {gap} 秒，落到：{where}')

    def report(i, n, r):
        mark = '✓' if r['ok'] else '×'
        note = pdf_fetch.REASONS.get(r['reason'], r['reason'])
        if r['reason'] == 'exists':
            note = '盘上已经有了，跳过'
        size = f'  {r["bytes"] // 1024} KB' if r['bytes'] else ''
        print(f'  [{i}/{n}] {mark} {r["doi"]}  {note}{size}')

    results = getpdf.fetch_many(dois, where=where, gap=gap, limit=limit,
                                on_each=report)

    print('\n结果：')
    for reason, n in sorted(getpdf.summarize(results).items(),
                            key=lambda kv: -kv[1]):
        label = '盘上已有' if reason == 'exists' else pdf_fetch.REASONS.get(reason, reason)
        print(f'  {n} 篇 · {label}')

    if any(r['reason'] == 'captcha' for r in results):
        print('\n⚠ 停在人机验证上了。去那个浏览器里点一下通过，再跑一次同样的命令 ——'
              '\n  已经拿到的不会重下，会接着没取到的往下走。')
    return 0
