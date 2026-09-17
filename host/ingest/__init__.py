# -*- coding: utf-8 -*-
"""host.ingest —— 落地即自动：正本一到，**不花大模型钱的那几步**自己做完。

**为什么有它**（2026-09-13 用户拍板）：
> 文献一下载正文和 SI 到本地，就自动一系列 MineRU 解析、文本拆分……
> 导入之后一系列不花钱的都自动做好了，要做到这些部分就够 LLM 读了。

一篇文献进了证据库（`raw/<id>/main.pdf`），到「模型能自己去读它」之间有三步，
每一步都不需要大模型：

| 步 | 做什么 | 花什么 | 产物 |
|---|---|---|---|
| 解析 | PDF → Markdown（MineRU）；SI 同理（docx 直接读字） | MineRU 额度（免费、量大） | `raw/<id>/parsed/full.md`、`si_parsed/full.md` |
| 骨架 | 全文 → 章节菜单，供模型「点菜」 | 零 | `curated/<id>/outline.json` |
| 向量化 | 切块 → 本地 bge-m3 → 向量库，供 `ask` 检索 | 零（本地） | `serving/vector_db/` |

**精读不在这里** —— 那是给人看的、花钱的，仍由用户打「待处理」标签触发。

## 它为什么住在 host/

跨了三个工具（getpdf 的正本、library 的骨架、ask 的向量化）+ 一个 adapter（pdf_parse）。
跨工具编排只能上浮到 host（硬规则 2 与 4）。

## 两个入口

    python -m host.ingest              # 把积压的全部做完（幂等，做过的跳过）
    python -m host.ingest --limit 5    # 先做 5 篇
    python -m host.ingest --loop       # 常驻：每 60 秒扫一次（看门狗拉的就是它，日常不用人管）
"""
import io
import os
import time

from shared.kernel import catalog, jobs, paths
from shared.kernel.log import get_logger

log = get_logger('ingest')

PRODUCER = 'ingest'


RETRY_AFTER = 24 * 3600      # 解析失败过的，隔一天再试一次（别每分钟都去敲 MineRU）


def _failed_recently(pid, step):
    """这一步最近一次是失败、且还没过重试间隔？

    2026-09-14 实测：一本 200 页以上的学位论文 MineRU 拒收（页数上限），
    积压判定只看「有正本没解析」，于是 watcher **每轮都去重试一次**，一分钟一次白敲。
    """
    try:
        r = jobs.last(pid, step)
    except Exception:
        return False
    if not r or r.get('status') != jobs.FAILED:
        return False
    return (time.time() - (r.get('finished_at') or r.get('started_at') or 0)) < RETRY_AFTER


def backlog():
    """还没做完免费三步的文献 id 列表：有正本没解析 / 有 SI 没解析 / 解析了没骨架。

    最近失败过的（如 MineRU 拒收的超长 PDF）先跳过，隔 `RETRY_AFTER` 再试。
    向量化的积压不在这里判（要开向量库才知道），`run_backlog` 里顺手做。
    """
    out = []
    for r in catalog.scan():
        pid = r['id']
        need_main = r['pdf'] and not r['fulltext'] and not _failed_recently(pid, 'parse')
        need_si = r['si'] and not r['si_fulltext'] and not _failed_recently(pid, 'parse_si')
        need_outline = r['fulltext'] and not os.path.isfile(paths.outline(pid))
        if need_main or need_si or need_outline:
            out.append(pid)
    return out


def failures():
    """最近失败、正在等重试的文献：[(id, step, error)]。给人看「哪几篇一直做不成」。"""
    out = []
    for r in catalog.scan():
        for step, need in (('parse', r['pdf'] and not r['fulltext']),
                           ('parse_si', r['si'] and not r['si_fulltext'])):
            if need and _failed_recently(r['id'], step):
                last = jobs.last(r['id'], step) or {}
                out.append((r['id'], step, (last.get('error') or '')[:100]))
    return out


def _parse_main(pid, say):
    """正文 PDF → parsed/full.md。已解析直接复用。返回 'done' / 'skip' / 'fail:<why>'。"""
    if os.path.isfile(paths.fulltext(pid)):
        return 'skip'
    pdf = paths.local_pdf(pid)
    if not os.path.isfile(pdf):
        return 'skip'
    from shared.adapters.pdf_parse import parse_pdf
    t0 = time.time()
    try:
        with jobs.track(pid, 'parse', producer=PRODUCER):
            parse_pdf(pdf, paths.parsed_dir(pid, create=True), reuse=True)
    except Exception as e:
        say(f'  × 正文解析失败：{type(e).__name__}: {str(e)[:120]}')
        return f'fail:{type(e).__name__}'
    ok = os.path.isfile(paths.fulltext(pid))
    say(f'  ✓ 正文解析 {time.time() - t0:.0f}s' if ok else '  × 解析跑完了但没产出 full.md')
    return 'done' if ok else 'fail:no_fullmd'


def _parse_si(pid, say):
    """SI → si_parsed/full.md。pdf 走 MineRU；docx 直接读字（含表格）。"""
    if os.path.isfile(paths.si_fulltext(pid)):
        return 'skip'
    src = paths.find_local_si(pid)
    if not src:
        return 'skip'
    out_dir = paths.si_parsed_dir(pid, create=True)
    t0 = time.time()
    try:
        from shared.adapters.pdf_parse import parse_document
        with jobs.track(pid, 'parse_si', producer=PRODUCER):
            parse_document(src, out_dir, reuse=True)      # pdf 走 MineRU，docx 直接读字
    except Exception as e:
        say(f'  × SI 解析失败：{type(e).__name__}: {str(e)[:120]}')
        return f'fail:{type(e).__name__}'
    ok = os.path.isfile(paths.si_fulltext(pid))
    say(f'  ✓ SI 解析 {time.time() - t0:.0f}s' if ok else '  × SI 解析没产出 full.md')
    return 'done' if ok else 'fail:no_fullmd'


def _outline(pid, say):
    """骨架（菜单）。纯脚本，几十毫秒。"""
    if not os.path.isfile(paths.fulltext(pid)):
        return 'skip'
    if os.path.isfile(paths.outline(pid)) and \
            os.path.getmtime(paths.outline(pid)) >= os.path.getmtime(paths.fulltext(pid)):
        return 'skip'
    from tools import library
    d = library.outline(pid, refresh=True)
    if d.get('available'):
        say(f'  ✓ 骨架 {len(d.get("sections") or [])} 节')
        return 'done'
    return 'fail:outline'


def _vectorize(pid, coll, have_main, have_si, say):
    """精层向量化（正文 + SI）。coll 为 None 时跳过（向量库没开）。"""
    if coll is None:
        return 'skip'
    from tools.ask import vectorize as V
    done = []
    try:
        new, n = V.deep_one(pid, coll, have_main, log=lambda s: None)
        if new:
            have_main.add(pid)
            done.append(f'正文 {n} 块')
        new, n = V.si_one(pid, coll, have_si, log=lambda s: None)
        if new:
            have_si.add(pid)
            done.append(f'SI {n} 块')
    except Exception as e:
        say(f'  × 向量化失败：{type(e).__name__}: {str(e)[:120]}')
        return f'fail:{type(e).__name__}'
    if done:
        say('  ✓ 向量化 ' + '、'.join(done))
        return 'done'
    return 'skip'


def _open_vectors(say):
    """打开向量库 + 两档已入库集合。开不了（Ollama 没跑 / 没装 chroma）就返回 None。"""
    try:
        from tools.ask import vectorize as V
        coll = V.get_collection()
        return coll, V._indexed_keys(coll, 'main'), V._si_indexed_keys(coll)
    except Exception as e:
        say(f'（向量库开不了，这次跳过向量化：{type(e).__name__}）')
        return None, set(), set()


def ingest_one(pid, vectors=None, say=print, prefix=''):
    """一篇做完免费三步 → dict(id, main, si, outline, vector)。**不抛异常**。"""
    pid = paths.check_key(pid)
    r = catalog.record(pid)
    say(f'{prefix}{pid}  {r["title"][:56] or "(无标题)"}')
    out = {'id': pid}
    out['main'] = _parse_main(pid, say)
    out['si'] = _parse_si(pid, say)
    out['outline'] = _outline(pid, say)
    coll, have_main, have_si = vectors or (None, set(), set())
    out['vector'] = _vectorize(pid, coll, have_main, have_si, say)
    return out


LOCK = 'ingest'          # 单实例锁名：手动全量跑和 watcher 顺手跑不能撞同一篇


def run_backlog(limit=None, say=print, with_vectors=True):
    """把积压的做完（最多 limit 篇）→ 计数。幂等：做过的一步都不重做。

    **同一时刻只许一份在跑**（`proc_lock`）：手动 `python -m host.ingest` 清积压时，
    watcher 每轮顺手做的那两篇会挑到同一篇，两个进程同时解析一篇 = 白花一次 MineRU。
    抢不到锁就返回全零，不排队不报错。
    """
    from shared.kernel.proc_lock import single_instance, release
    counts = {'parsed': 0, 'si_parsed': 0, 'outlined': 0, 'vectorized': 0, 'failed': 0}
    if not single_instance(LOCK):
        say('另一份落地流水线正在跑，这次让开')
        return counts
    try:
        return _run_backlog(limit, say, with_vectors, counts)
    finally:
        release(LOCK)
        from shared.adapters import vectordb
        vectordb.close_all()       # 常驻进程别抱着向量库连接过夜（见 vectordb.close_all）


def _run_backlog(limit, say, with_vectors, counts):
    todo = backlog()
    if with_vectors:
        # 向量化的积压单独算：解析过但没入库的也要补
        try:
            vectors = _open_vectors(say)
            coll, have_main, have_si = vectors
            if coll is not None:
                for r in catalog.scan():
                    if r['id'] in todo:
                        continue
                    if (r['fulltext'] and r['id'] not in have_main) or \
                            (r['si_fulltext'] and r['id'] not in have_si):
                        todo.append(r['id'])
        except Exception:
            vectors = (None, set(), set())
    else:
        vectors = (None, set(), set())
    if limit:
        todo = todo[:int(limit)]
    say(f'积压 {len(todo)} 篇' if todo else '没有积压，证据库里每篇都能读了')
    from shared.kernel import heartbeat
    for i, pid in enumerate(todo, 1):
        r = ingest_one(pid, vectors, say, prefix=f'[{i}/{len(todo)}] ')
        heartbeat.progress('ingest')
        counts['parsed'] += r['main'] == 'done'
        counts['si_parsed'] += r['si'] == 'done'
        counts['outlined'] += r['outline'] == 'done'
        counts['vectorized'] += r['vector'] == 'done'
        counts['failed'] += any(str(v).startswith('fail') for v in r.values())
    if todo:
        heartbeat.done('ingest')
    return counts
