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
    python -m tools.getpdf 10.1016/xxx --out D:/somewhere

  收进 Zotero（会写你的库）:
    python -m tools.getpdf --file dois.txt --to-zotero             # 默认「建库」用途
    python -m tools.getpdf 10.1016/xxx --to-zotero --purpose 精读   # 标成重点文章
    python -m tools.getpdf --file dois.txt --to-zotero --with-si   # 连补充材料一起

**跑之前**：那台机器上要有一个带调试口启动的浏览器，**里面得有人过过一次人机验证**
（机构订阅靠出口 IP 自动生效，不用登录；人机验证的通行证跟着浏览器的用户资料走）。
专开一个就行，别跟日常那个抢 —— 双击 `launch/取全文用的浏览器.bat`，或者：

    msedge  --remote-debugging-port=9333 --user-data-dir=<给它单独一个文件夹>
    chrome  --remote-debugging-port=9333 --user-data-dir=<给它单独一个文件夹>

默认很慢（每篇间隔 20 秒、单次最多 25 篇），这是**故意的**：
出版商封的是整个机构的 IP，代价全校担。要快请自己显式加 --gap / --limit。

`--to-zotero` 做四件事，每件都**幂等**（同一批跑两遍 = 跑一遍）：
查库里有没有 → 没有就按 Crossref 元数据建条目 → 挂正文 PDF（已有就不重复挂）
→ 放进「<顶层合集>/建库用」或「/重点精读」。
**不打精读标签、不触发精读** —— 那是花钱的事，什么时候开始由你决定。

`--with-si` 连补充材料一起取。**值得开** —— 本项目验证过：投料量、配比、
温度时间几乎只写在 SI 里。只要「实验那份」，演示视频一律不下
（既省配额，解析器也拿视频没办法）。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
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
        from shared.kernel import paths, role
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
        rs = F.many(keys, allow_fetch=allow,
                    progress=paths.runtime('fulltext_progress.json'))
        print(F.summarize(rs))
        return 0 if all(r['ok'] for r in rs) else 1

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

    to_zotero = flag('--to-zotero')
    with_si = flag('--with-si')
    purpose = opt('--purpose') or '建库'
    if to_zotero:
        if purpose not in getpdf.PURPOSES:
            print(f'--purpose 只能是 {" / ".join(getpdf.PURPOSES)}，'
                  f'给的是「{purpose}」')
            return 2
        # 写 Zotero 是不可逆的副作用 —— 守卫写在函数体里，不能写模块顶层（强制规范 #7）
        role.require_prod('把文献收进你的 Zotero 库（建条目、挂 PDF、归合集）',
                          force=flag('--force'))
        # **先确认拿得到密钥再动手**，别等 PDF 都下完了才在入库那步炸出 traceback。
        # 最常见的原因不是「没配」，而是**远程 SSH 会话打不开 Windows 凭据库** ——
        # 密钥明明存着，`get_key` 却返回空串（2026-09-06 就这么炸过一次）。
        from shared.kernel.config import get_key
        if not get_key('ZOTERO_API_KEY'):
            print('读不到 Zotero 的密钥，没法写库 —— 先不下载了，省得白跑一趟。')
            print('  ① 如果你是**远程连过来**跑的：SSH 会话打不开 Windows 凭据库，')
            print('     密钥存着也读不到。换成 `job` 通道跑，或者直接在那台机器上跑。')
            print('  ② 如果是在本机跑：去控制面板把 Zotero 的密钥填上。')
            print('  （不带 --to-zotero 只取 PDF 不受影响。）')
            return 1

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
    if to_zotero:
        _stash_all(results, purpose, with_si=with_si)
    return 0


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


def _stash_all(results, purpose, with_si=False):
    """把拿到的那些收进 Zotero，逐篇报告。"""
    got = [r for r in results if r['ok'] and r['path']]
    if not got:
        print('\n没有可以收进 Zotero 的（这批一篇都没拿到）。')
        return
    sub, why = getpdf.PURPOSES[purpose]
    print(f'\n收进 Zotero → 「{getpdf.collection_top()}/{sub}」（{why}）')

    words = {'created': '新建了条目并挂上 PDF', 'attached': '条目本来就有，补了 PDF',
             'exists': '本来就在库里', 'failed': '没成'}
    print('  先取一份全库 DOI 索引用来查重…')
    index = getpdf.doi_index()
    print(f'  库里现有 {len(index)} 篇带 DOI 的文献')
    col = getpdf.ensure_tree(purpose)
    counts = {}
    for i, r in enumerate(got, 1):
        s = getpdf.stash(r['doi'], r['path'], purpose=purpose,
                         col_key=col, index=index)
        counts[s['action']] = counts.get(s['action'], 0) + 1
        mark = '✓' if s['ok'] else '×'
        note = f'  （{s["note"]}）' if s['note'] else ''
        line = (f'  [{i}/{len(got)}] {mark} {s["doi"]}  '
                f'{words.get(s["action"], s["action"])}{note}')
        if with_si and s['ok'] and s['item']:
            si = r.get('si') or {}
            if si.get('ok') and si.get('path'):
                did, why = getpdf.attach_si(s['item'], si['path'])
                line += '  + SI 挂上了' if did else f'  + SI：{why}'
            else:
                line += '  + 没有 SI'
        print(line)

    print('\n入库结果：')
    for a, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f'  {n} 篇 · {words.get(a, a)}')
    print('\n没有打精读标签，也没有触发精读 —— 要精读的话你在 Zotero 里打「待处理」。')
