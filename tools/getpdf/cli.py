# -*- coding: utf-8 -*-
"""取全文的命令行入口（只解析参数，一行业务逻辑都没有）。

用法:
    python -m tools.getpdf --probe                       # 浏览器在不在（先跑这个）
    python -m tools.getpdf 10.1021/xxx --fulltext        # DOI → 可读全文（四层回退）
    python -m tools.getpdf 10.1021/xxx --fulltext --no-fetch   # 只看手上有没有，零代价
    python -m tools.getpdf 10.1016/j.cej.2025.164092     # 取一篇
    python -m tools.getpdf 10.1016/xxx 10.1002/yyy       # 取几篇
    python -m tools.getpdf --file dois.txt               # 从文件读，一行一个
    python -m tools.getpdf --file dois.txt --gap 30      # 每篇之间等 30 秒
    python -m tools.getpdf --file dois.txt --limit 10    # 这次最多取 10 篇
    python -m tools.getpdf 10.1016/xxx --out D:/somewhere   # 只下到某个目录，不收进证据库

    python -m tools.getpdf --补SI [--limit 20] [--gap 20] # 给证据库里没取过 SI 的补 SI（幂等，停了再跑接着补）

**取到的收进证据库**（raw/<id>/main.pdf + si.* + 目录登记）。2026-10-13 起 Zotero 移出平台，不再有「推到 Zotero」。

**跑之前**：那台机器上要有一个带调试口启动的浏览器，**里面得有人过过一次人机验证**
（机构订阅靠出口 IP 自动生效，不用登录；人机验证的通行证跟着浏览器的用户资料走）。
专开一个就行，别跟日常那个抢 —— 双击 `launch/取全文用的浏览器.bat`，或者：

    msedge  --remote-debugging-port=9333 --user-data-dir=<给它单独一个文件夹>
    chrome  --remote-debugging-port=9333 --user-data-dir=<给它单独一个文件夹>

默认很慢（每篇间隔 20 秒、单次最多 25 篇），这是**故意的**：
出版商封的是整个机构的 IP，代价全校担。要快请自己显式加 --gap / --limit。

`--with-si` 连补充材料一起取。**值得开** —— 本项目验证过：投料量、配比、
温度时间几乎只写在 SI 里。只要「实验那份」，演示视频一律不下
（既省配额，解析器也拿视频没办法）。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

import io

from shared.adapters import pdf_fetch
from shared.kernel import role
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

    # ── 跨付费墙的原子入口（2026-09-08）─────────────────────────────
    # 后台作业也走这条路（MCP 的 paper_fulltext 就是 spawn 它）。
    if flag('--fulltext'):
        from shared.kernel import paths
        from tools.getpdf import fulltext as F
        keys = list(positionals())
        if not keys:
            # ⚠ 位置参数必须在选项**前面**（shared.kernel.cli 的约定）——
            # 我第一次真跑时就把顺序写反了，命令直接空跑（2026-09-08）
            print('用法：python -m tools.getpdf <DOI> [DOI...] --fulltext')
            return 2
        allow = not flag('--no-fetch')
        if allow:
            # 会向出版商发真实请求 + 花 MineRU 额度 —— 编程端默认拦住
            role.require_prod('取全文（向出版商取 PDF + MineRU 解析）',
                              force=flag('--force'))
        # --limit：一次处理几篇（默认 3，MCP 的 /science 面一次最多交 25 篇）。
        # 只是「一批几篇」，风控靠的串行 + 20 秒间隔在 many() 里，不受它影响
        from tools.getpdf import notify
        rs = F.many(keys, allow_fetch=allow, limit=int(opt('--limit') or 3),
                    progress=paths.runtime('fulltext_progress.json'), notify=notify.desktop)
        print(F.summarize(rs))
        return 0 if all(r['ok'] for r in rs) else 1

    if flag('--补SI'):
        # 给证据库里「没取过 SI」的文献补 SI；幂等，停了再跑接着补
        if not getpdf.probe().get('ok'):
            print('取全文用的浏览器没开：先双击 launch/取全文用的浏览器.bat')
            return 1
        getpdf.fill_si(gap=int(opt('--gap') or getpdf.GAP), limit=int(opt('--limit') or 0) or None)
        return 0

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

    with_si = flag('--with-si')
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

    if with_si:
        _fetch_si_all(results, where, gap)
    if not opt('--out'):
        _land_all(results)              # 收进证据库：正本 + 目录。--out 时是「只下到那里」
    return 0


def _land_all(results):
    """把拿到的正文 / SI 收进证据库（复制成正本 + 登记目录）。不联网。"""
    got = [r for r in results if r['ok'] and r['path']]
    if not got:
        return
    print('\n收进证据库：')
    counts = {}
    for r in got:
        si = (r.get('si') or {}).get('path') or None
        l = getpdf.land(r['doi'], with_si=bool(si), allow_fetch=False,
                        pdf_path=r['path'], si_path=si)
        r['id'] = l.get('id')
        counts[l['action']] = counts.get(l['action'], 0) + 1
        word = {'landed': '落成正本', 'exists': '早就在', 'failed': '没成'}[l['action']]
        print(f'  {"✓" if l["ok"] else "×"} {r["doi"]} → {l["id"]}  {word}'
              + ('  +SI' if l.get('si') else '') + (f'  （{l["note"]}）' if l['note'] else ''))
    print('  ' + '，'.join(f'{n} 篇{ {"landed": "新落地", "exists": "已有", "failed": "失败"}[a] }'
                         for a, n in counts.items()))


def _fetch_si_all(results, where, gap):
    """给拿到正文的那些补上 SI。"""
    import time
    got = [r for r in results if r['ok'] and r['path']]
    if not got:
        return
    print('\n再取补充材料（只要实验那份，视频不下）：')
    for i, r in enumerate(got, 1):
        si = getpdf.fetch_si_one(r['doi'], where)
        r['si'] = si
        if si['reason'] == 'exists':
            note = '盘上已经有了，跳过'
        elif si['ok']:
            note = f'拿到了  {si["bytes"] // 1024} KB'
        else:
            note = pdf_fetch.REASONS.get(si['reason'], si['reason'])
        print(f'  [{i}/{len(got)}] {"✓" if si["ok"] else "×"} {r["doi"]}  {note}')
        if i < len(got) and si['reason'] != 'exists':
            time.sleep(gap)
