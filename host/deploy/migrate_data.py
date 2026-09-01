# -*- coding: utf-8 -*-
"""把老的 `workflow_data/` 一次性搬成新的五层 `data/`（R6 窗，2026-08-31）。

**为什么是一个脚本而不是手敲几条 mv**：
A 机的库里只有一两篇，手搬也就算了；**B 机（主力机）才是数据的权威副本**，
那边有几百篇、几个 GB。同一次搬家必须在两台机器上产生**一模一样**的结果，
而且必须「先复制、核对、再删原目录」——这三件事写成脚本才可重复、可核对。

搬法（对照 `shared/kernel/paths.py` 顶部那段五层说明）：

    workflow_data/library/<KEY>/parsed      → data/raw/<KEY>/parsed
    workflow_data/library/<KEY>/si_parsed   → data/raw/<KEY>/si_parsed
    workflow_data/library/<KEY>/其余文件    → data/curated/<KEY>/
    workflow_data/structured                → data/serving/structured
    workflow_data/vector_db                 → data/serving/vector_db
    workflow_data/direction                 → data/serving/direction
    workflow_data/state.db* papers.db*      → data/state/
    workflow_data/evalset.json              → data/state/evalset.json
    workflow_data/_last_search.json         → data/state/_last_search.json
    workflow_data/待删条目清单.*            → data/state/
    workflow_data/structured_bak_<stamp>    → data/backup/structured_<stamp>
    workflow_data/_incoming                 → data/raw/_incoming
    workflow_data/logs                      → data/logs
    workflow_data/backup                    → data/backup

**一篇文献现在占两个目录**（raw 一半、curated 一半），因为它跨两层。
切口划在目录边界上而不是文件上：`full.md` 留在 `parsed/` 里跟着 `images/`
和 `*_origin.pdf` 一起走 —— 理由写在 `paths.py` 顶部。

用法：
    python host/deploy/migrate_data.py            # 只看要搬什么（不动任何东西）
    python host/deploy/migrate_data.py --apply    # 复制 + 逐个核对
    python host/deploy/migrate_data.py --apply --remove-old   # 核对通过后删原目录

⚠ `--remove-old` 是唯一会删东西的开关，而且**只在核对全过时才会执行**。
不加它的话原目录原封不动留着，确认无误再跑一次带它的。
"""
import os
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import paths
from shared.kernel.cli import flag, wants_help

OLD = os.path.join(paths.ROOT, 'workflow_data')
NEW = paths.DATA


def _plan_one_paper(key, out):
    """一篇文献拆成 raw / curated 两半。"""
    src = os.path.join(OLD, 'library', key)
    for name in sorted(os.listdir(src)):
        s = os.path.join(src, name)
        if name in ('parsed', 'si_parsed'):
            out.append((s, os.path.join(NEW, 'raw', key, name)))
        else:
            out.append((s, os.path.join(NEW, 'curated', key, name)))


def plan():
    """返回 [(源, 目标)]，都是绝对路径。源不存在的条目不会出现在结果里。"""
    out = []
    if not os.path.isdir(OLD):
        return out

    lib = os.path.join(OLD, 'library')
    if os.path.isdir(lib):
        for key in sorted(os.listdir(lib)):
            if os.path.isdir(os.path.join(lib, key)):
                _plan_one_paper(key, out)

    def mv(rel, dst):
        s = os.path.join(OLD, rel)
        if os.path.exists(s):
            out.append((s, dst))

    for d in ('structured', 'vector_db', 'direction'):
        mv(d, os.path.join(NEW, 'serving', d))
    mv('_incoming', os.path.join(NEW, 'raw', '_incoming'))
    mv('logs', os.path.join(NEW, 'logs'))
    mv('backup', os.path.join(NEW, 'backup'))

    # state 层：名字不定的（state.db-wal 之类）靠前缀扫
    for name in sorted(os.listdir(OLD)):
        if name.startswith(('state.db', 'papers.db', '待删条目清单.')) \
                or name in ('evalset.json', '_last_search.json'):
            mv(name, os.path.join(NEW, 'state', name))
        elif name.startswith('structured_bak_'):
            mv(name, os.path.join(NEW, 'backup', 'structured_' + name[len('structured_bak_'):]))
    return out


def _weigh(path):
    """(文件数, 总字节)。单个文件就是 (1, size)。"""
    if os.path.isfile(path):
        return 1, os.path.getsize(path)
    n = size = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                size += os.path.getsize(os.path.join(dirpath, f))
                n += 1
            except OSError:
                pass
    return n, size


def _mb(b):
    return f'{b / 1024 / 1024:.1f} MB'


def copy_all(moves, log=print):
    """复制。已存在的目标**不覆盖**，直接判为失败 —— 免得搬了一半再搬一次搞混。"""
    for src, dst in moves:
        if os.path.exists(dst):
            raise SystemExit(f'✗ 目标已存在，先处理掉再来：{dst}')
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        log(f'  复制 {os.path.relpath(src, paths.ROOT)} → {os.path.relpath(dst, paths.ROOT)}')


# 「搬完之后目标还会继续长」的那一类：日志。别处一律按字节严格核对。
#
# 为什么要有这个例外（2026-09-01 实测撞上）：R6 搬完之后平台照常在跑，
# 新的日志行一直往**新位置**写。过一天再来核对，`data/logs` 比
# `workflow_data/logs` 大了 44 KB —— 严格核对当然不过，
# 而这恰恰说明搬对了（大家都在用新位置）。
#
# 但**不能因此就不核对**：文件数还是要一模一样（少一个文件 = 真的漏搬了），
# 字节数只放宽一个方向（目标只许比源大，小了说明搬丢了内容）。
_GROWS_AFTER_MOVE = ('logs',)


def _loose(src):
    return os.path.basename(src.rstrip(os.sep)) in _GROWS_AFTER_MOVE


def verify(moves, log=print):
    """逐条核对「文件数与总字节完全一致」（日志目录只要求「文件数一致且没变小」）。"""
    bad = []
    for src, dst in moves:
        (sn, sb), (dn, db) = _weigh(src), _weigh(dst)
        ok = (sn == dn and db >= sb) if _loose(src) else ((sn, sb) == (dn, db))
        if not ok:
            bad.append((src, dst))
        elif _loose(src) and db != sb:
            log(f'  · {os.path.relpath(src, paths.ROOT)}：{sn} 个文件都在，'
                f'新位置多了 {_mb(db - sb)}（搬完之后一直在往新位置写日志，正常）')
    for src, dst in bad:
        log(f'  ✗ 对不上：{os.path.relpath(src, paths.ROOT)}  {_weigh(src)} vs {_weigh(dst)}')
    return not bad


def main():
    if wants_help():
        print(__doc__)
        return 0
    apply_ = flag('--apply')
    remove_old = flag('--remove-old')

    if not os.path.isdir(OLD):
        print(f'没有 {os.path.relpath(OLD, paths.ROOT)}/ —— 已经搬过了，或本机没有数据。')
        return 0

    moves = plan()
    n_files = sum(_weigh(s)[0] for s, _d in moves)
    n_bytes = sum(_weigh(s)[1] for s, _d in moves)
    print(f'待搬 {len(moves)} 项，共 {n_files} 个文件，{_mb(n_bytes)}')
    for src, dst in moves:
        print(f'  {os.path.relpath(src, paths.ROOT)}  →  {os.path.relpath(dst, paths.ROOT)}')

    if not apply_:
        print('\n这是预演，什么都没动。确认无误后加 --apply。')
        return 0

    # 已经搬过一轮、只是没删原目录 —— 这是最常见的一种「第二次运行」。
    #
    # ⚠ 这是设计上漏掉的一条路（R6 窗被它拦住了，原目录多留了一天）：
    #   `copy_all()` 见到目标已存在就直接退出，于是**永远走不到核对与删除那两步** ——
    #   而「先复制、再核对、核对全过才删」这套流程的最后一步恰恰只能靠它们。
    #   结果就是：搬完之后想删原目录，唯一的正规入口是死路。
    #   这里补上「全都搬过了 → 跳过复制，直接核对」，让流程能走完。
    done = [d for _s, d in moves if os.path.exists(d)]
    if done and len(done) == len(moves):
        print('\n目标全部已存在 —— 上一轮搬过了，这次只核对（不重复复制）。')
    elif done:
        raise SystemExit(
            f'✗ 搬了一半：{len(done)}/{len(moves)} 项的目标已存在。\n'
            '  这种状态不该自动继续 —— 先人工确认已存在的那些是不是这次要的，'
            '再决定删哪边。')
    else:
        print('\n复制中…')
        copy_all(moves)
    print('\n核对中…')
    if not verify(moves):
        print('\n✗ 核对没过。**原目录一个字节都没动**，照上面的差异排查。')
        return 1
    print(f'✓ {len(moves)} 项全部一致。')

    if not remove_old:
        print(f'\n原目录留着没删。确认新目录没问题后，再跑一次带 --remove-old。')
        return 0
    shutil.rmtree(OLD)
    print(f'✓ 已删除 {os.path.relpath(OLD, paths.ROOT)}/')
    return 0


if __name__ == '__main__':
    sys.exit(main())
