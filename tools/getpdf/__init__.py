# -*- coding: utf-8 -*-
"""getpdf · 一批 DOI → 一批 PDF 落地（本工具的全部业务逻辑都在这个文件）

**解决的真实问题**：`discover` 已经能找出「该读哪些」，`deepread` 已经能精读，
中间「把这几十篇的正文弄到手」一直是人一篇篇点。这块把中间那段补上。

**它不负责的事**（都是刻意的）：
  - 怎么拿到 PDF → `shared.adapters.pdf_fetch`（借真实浏览器，见那块的 CLAUDE.md）
  - 元数据 → `shared.adapters.crossref`
  - 写进 Zotero → **还没做**。`zotero_client` 目前是只读的，没有建条目/挂附件的能力，
    那是下一步要新加的适配件，不是这里凑合。所以本工具现在只把 PDF 落到磁盘。

**为什么默认慢**：出版商对短时间大量下载有风控，被掐的是**整个机构的 IP**，
不是某个账号 —— 代价由全校承担。所以 `GAP` 和 `LIMIT` 的默认值取保守值，
宁可慢，不可惹。想快的人得自己显式改，改的时候就会看见这段话。

对外接口：
  - probe()                       → 浏览器在不在 → dict
  - fetch_many(dois, ...)         → 逐篇取，返回每篇的结果 dict 列表
  - safe_name(doi)                → DOI → 能当文件名的样子
"""
import io
import os
import time

from shared.adapters import pdf_fetch
from shared.kernel import paths
from shared.kernel.log import get_logger

log = get_logger('getpdf')

# 保守默认值 —— 见模块 docstring 里为什么。
GAP = 20        # 每篇之间等几秒
LIMIT = 25      # 一次最多取几篇


def safe_name(doi):
    """DOI → 文件名。`/` 换成 `_`，其余不动 —— 要能一眼看出是哪篇。"""
    out = []
    for ch in (doi or '').strip():
        out.append(ch if (ch.isalnum() or ch in '.-_') else '_')
    return ''.join(out) or 'unknown'


def probe():
    """那个浏览器在不在 → dict(ok, cdp, pages/error)。取全文之前先问这一句。"""
    return pdf_fetch.probe()


def out_dir(create=False):
    """PDF 落在哪：临时处理区。**不写死路径**（红线 #4）。"""
    d = os.path.join(paths.INCOMING, 'getpdf')
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def fetch_one(doi, where=None):
    """取一篇 → dict(doi, ok, reason, path, title, landing, bytes)。

    已经在盘上的直接跳过（`reason='exists'`）—— 重跑一批不该重下已有的，
    那既慢又是白白多敲一次出版商。
    """
    where = where or out_dir(create=True)
    path = os.path.join(where, safe_name(doi) + '.pdf')
    if os.path.exists(path) and os.path.getsize(path) > 1024:
        return {'doi': doi, 'ok': True, 'reason': 'exists', 'path': path,
                'title': '', 'landing': '', 'bytes': os.path.getsize(path)}

    r = pdf_fetch.fetch(doi)
    if not r['ok']:
        log.info(f'{doi} 没拿到：{r["reason"]}')
        return {'doi': doi, 'ok': False, 'reason': r['reason'], 'path': '',
                'title': r.get('title', ''), 'landing': r.get('landing', ''),
                'bytes': 0}

    os.makedirs(where, exist_ok=True)
    with io.open(path, 'wb') as fh:
        fh.write(r['pdf'])
    log.info(f'{doi} → {path}（{len(r["pdf"])} 字节）')
    return {'doi': doi, 'ok': True, 'reason': 'ok', 'path': path,
            'title': r.get('title', ''), 'landing': r.get('landing', ''),
            'bytes': len(r['pdf'])}


def fetch_many(dois, where=None, gap=GAP, limit=LIMIT, on_each=None):
    """逐篇取。返回结果列表。

    **撞上人机验证就停**，不是跳过 —— 验证码是「人去点一下，然后整批都会顺」，
    继续硬跑只会把剩下的全废掉，还多敲了出版商一堆次。
    """
    todo = [d.strip() for d in dois if pdf_fetch.is_doi(d.strip())][:limit]
    where = where or out_dir(create=True)
    results = []
    for i, doi in enumerate(todo):
        r = fetch_one(doi, where)
        results.append(r)
        if on_each:
            on_each(i + 1, len(todo), r)
        if r['reason'] == 'captcha':
            log.info('撞上人机验证，停在这里等人去点')
            break
        # 最后一篇后面不用等；从盘上直接命中的也不用等（没敲出版商）
        if i + 1 < len(todo) and r['reason'] != 'exists':
            time.sleep(gap)
    return results


def summarize(results):
    """一批结果 → 按 reason 分组的计数，给人看的。"""
    counts = {}
    for r in results:
        counts[r['reason']] = counts.get(r['reason'], 0) + 1
    return counts
