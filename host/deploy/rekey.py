# -*- coding: utf-8 -*-
"""rekey · 证据库里还用 Zotero 编号命名的文献，改成按 DOI 命名（跟 Zotero 拆开的第一步，2026-10-12 用户定）。

用法（只在主力机跑）：
    python -m host.deploy.rekey                       # 只看计划，什么都不改
    python -m host.deploy.rekey --apply --limit 3     # 先改 3 篇试试
    python -m host.deploy.rekey --apply               # 改完剩下的
    python -m host.deploy.rekey --undo <日志路径>       # 按日志原样改回去

一篇 `old → new` 要动的地方（2026-10-12 在主力机只读盘点过）：
    data/raw/old、data/curated/old 两个目录改名（目录里的文件不写死自己的编号，抽查 124 个文件为证）
    目录卡 meta.json：key 改成 new，zotero_key 记 old（旧编号靠它继续认得：`catalog.resolve`）
    structured/old.json → new.json
    任务记录库 state.db 的 runs.item_key
    向量库里每块的元数据 key（`vectordb.rekey`）
    作者索引 oa_index.json 的键
    人写的 / 要留的文本：evalset.json、structured/*.md（对比表、概念矩阵）里出现的 old
改完：按新索引重挂团队，重建数值库 papers.db（都是可重建的索引）。

没 DOI 的不动（换不了）。目标目录已存在的跳过并报出来（同一篇两份，要人看）。
动手前把会被改写的小文件（state.db、evalset、对比表、两份索引）整份备份进 `paths.rekey_backup(时间)`，
每做完一篇就往同目录的 `log.json` 追加一条 —— 中途断了，已做的都在日志里，`--undo` 照着改回去。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

import io
import json
import re
import shutil
import sqlite3
import time

from shared.kernel import catalog, paths, role
from shared.kernel.cli import flag, opt, wants_help


def plan():
    """[(old, new, doi)] 与 [(old, 原因)] —— 要改的与跳过的。"""
    todo, skip = [], []
    for r in catalog.scan():
        old = r['id']
        if not paths.is_zotero_key(old):
            continue
        if not r['doi']:
            skip.append((old, '没有 DOI'))
            continue
        try:
            new = paths.paper_id_from_doi(r['doi'])
        except paths.BadKeyError:
            skip.append((old, f'DOI 不规范：{r["doi"]}'))
            continue
        if os.path.isdir(paths.paper_dir(new)) or os.path.isdir(paths.paper_raw_dir(new)):
            skip.append((old, f'{new} 已存在（同一篇两份，要人看）'))
            continue
        todo.append((old, new, r['doi']))
    return todo, skip


def _text_files():
    """会提到文献编号、又不是可重建索引的文本文件。"""
    out = [paths.evalset()]
    if os.path.isdir(paths.STRUCTURED):
        out += [os.path.join(paths.STRUCTURED, f) for f in os.listdir(paths.STRUCTURED) if f.endswith('.md')]
    return [p for p in out if os.path.isfile(p)]


def backup(stamp):
    d = paths.rekey_backup(stamp)
    os.makedirs(d, exist_ok=True)
    for p in [paths.state_db(), paths.oa_index(), paths.team_links()] + _text_files():
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(d, os.path.basename(p)))
    return d


def _replace_in_text(old, new):
    n = 0
    pat = re.compile(r'(?<![A-Za-z0-9_])' + re.escape(old) + r'(?![A-Za-z0-9_])')
    for p in _text_files():
        t = io.open(p, encoding='utf-8').read()
        t2, k = pat.subn(new, t)
        if k:
            io.open(p, 'w', encoding='utf-8', newline='').write(t2)
            n += k
    return n


def _rekey_oaindex(old, new):
    p = paths.oa_index()
    if not os.path.isfile(p):
        return False
    d = json.load(io.open(p, encoding='utf-8'))
    if old not in d.get('papers', {}):
        return False
    d['papers'][new] = d['papers'].pop(old)
    json.dump(d, io.open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    return True


def move_one(old, new, store=None, con=None):
    """改一篇。返回做了哪些事（写进日志，撤回时照着反着做）。"""
    did = {'old': old, 'new': new}
    for layer, fn in (('curated', paths.paper_dir), ('raw', paths.paper_raw_dir)):
        src, dst = fn(old), fn(new)
        if os.path.isdir(src):
            if os.path.exists(dst):
                raise RuntimeError(f'{dst} 已存在，停下')
            os.rename(src, dst)
            did[layer] = True
    meta = catalog.read_meta(new)
    zk = meta.get('zotero_key') or (old if paths.is_zotero_key(old) else '')
    catalog.register(new, overwrite=True, key=new, zotero_key=zk)
    s_old, s_new = paths.structured(old), paths.structured(new)
    if os.path.isfile(s_old) and not os.path.exists(s_new):
        os.rename(s_old, s_new)
        did['structured'] = True
    if con is not None:
        did['state_rows'] = con.execute('update runs set item_key=? where item_key=?', (new, old)).rowcount
        con.commit()
    if store is not None:
        did['vector_chunks'] = store.rekey(old, new)
    did['oa_index'] = _rekey_oaindex(old, new)
    did['text_hits'] = _replace_in_text(old, new)
    return did


def _open_stores():
    from shared.adapters import vectordb
    store = vectordb.open_store() if vectordb.exists() else None
    con = sqlite3.connect(paths.state_db()) if os.path.isfile(paths.state_db()) else None
    return store, con


def _after():
    """改完重挂团队、重建数值库（都是可重建的索引）。"""
    from tools.library import teams
    teams.build()
    from shared.kernel import subproc
    subproc.run([sys.executable, '-m', 'tools.paperdb', '--rebuild'], timeout=600)


def apply(limit=None):
    todo, skip = plan()
    if limit:
        todo = todo[:limit]
    stamp = time.strftime('%Y%m%d-%H%M%S')
    d = backup(stamp)
    log_path = os.path.join(d, 'log.json')
    print(f'备份在 {d}；这次改 {len(todo)} 篇')
    store, con = _open_stores()
    done = []
    try:
        for i, (old, new, doi) in enumerate(todo, 1):
            r = move_one(old, new, store, con)
            done.append(r)
            json.dump(done, io.open(log_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            print(f'  {i}/{len(todo)} {old} → {new}  块 {r.get("vector_chunks", 0)} · 记录 {r.get("state_rows", 0)}'
                  f' · 文本 {r["text_hits"]}')
    finally:
        if con is not None:
            con.close()
    catalog._cache_clear()
    _after()
    print(f'完成 {len(done)} 篇；撤回：python -m host.deploy.rekey --undo "{log_path}"')
    return 0


def undo(log_path):
    done = json.load(io.open(log_path, encoding='utf-8'))
    store, con = _open_stores()
    try:
        for r in reversed(done):
            back = move_one(r['new'], r['old'], store, con)
            print(f'  {r["new"]} → {r["old"]}  块 {back.get("vector_chunks", 0)}')
    finally:
        if con is not None:
            con.close()
    catalog._cache_clear()
    _after()
    print(f'已按日志改回 {len(done)} 篇')
    return 0


def main():
    if wants_help():
        print(__doc__)
        return 0
    if opt('--undo'):
        role.require_prod('把文献文件夹的编号按日志改回去', force=flag('--force'))
        return undo(opt('--undo'))
    if flag('--apply'):
        role.require_prod('把文献文件夹从 Zotero 编号改成按 DOI 命名', force=flag('--force'))
        return apply(int(opt('--limit', 0)) or None)
    todo, skip = plan()
    print(f'要改 {len(todo)} 篇，跳过 {len(skip)} 篇（只看计划，什么都没改；加 --apply 才动手）')
    for old, new, doi in todo[:10]:
        print(f'  {old} → {new}')
    if len(todo) > 10:
        print(f'  …… 另 {len(todo) - 10} 篇')
    for old, why in skip:
        print(f'  跳过 {old}：{why}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
