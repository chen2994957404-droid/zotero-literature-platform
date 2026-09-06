# -*- coding: utf-8 -*-
"""getpdf · 一批 DOI → 一批 PDF 落地（本工具的全部业务逻辑都在这个文件）

**解决的真实问题**：`discover` 已经能找出「该读哪些」，`deepread` 已经能精读，
中间「把这几十篇的正文弄到手」一直是人一篇篇点。这块把中间那段补上。

**它不负责的事**（都是刻意的）：
  - 怎么拿到 PDF → `shared.adapters.pdf_fetch`（借真实浏览器，见那块的 CLAUDE.md）
  - 元数据 → `shared.adapters.crossref`
  - 写进 Zotero → `shared.adapters.zotero_client`（`--to-zotero` 时才碰）

**为什么默认慢**：出版商对短时间大量下载有风控，被掐的是**整个机构的 IP**，
不是某个账号 —— 代价由全校承担。所以 `GAP` 和 `LIMIT` 的默认值取保守值，
宁可慢，不可惹。想快的人得自己显式改，改的时候就会看见这段话。

对外接口：
  - probe()                       → 浏览器在不在 → dict
  - fetch_many(dois, ...)         → 逐篇取，返回每篇的结果 dict 列表
  - safe_name(doi)                → DOI → 能当文件名的样子
  - doi_index()                   → 全库 DOI → 条目 key，查重用
  - stash(doi, pdf, purpose)      → 收进 Zotero（查重 → 建条目 → 挂 PDF → 归合集）
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


# ── 收进 Zotero ────────────────────────────────────────────────────────────
# 这一段是「有副作用」的那一半：会往用户真实的库里写东西。
# 每一步都做成**幂等**的 —— 同一批 DOI 跑两遍，结果必须跟跑一遍一样。
# 不幂等的后果不是「白跑」，是库里多出一堆重复条目，而重复条目**只能人工合并**
# （删掉一个会丢掉它身上的合集和标签，这是 Zotero 的已知行为）。

# 合集名字走 config，用户可以在控制面板改，改了不用动代码（红线 #3）。
DEFAULT_TOP = 'LLM导入'
PURPOSES = {
    '建库': ('建库用', '只解析 + 向量化，补数据库用，不精读'),
    '精读': ('重点精读', '向量化基础上还要精读的重点文章'),
}


def collection_top():
    """自动导入的顶层合集名。"""
    from shared.kernel import config
    return config.get_key('GETPDF_COLLECTION_TOP', default='') or DEFAULT_TOP


def doi_index(limit=100):
    """全库的 DOI → 条目 key（小写键）。**一次取回，整批复用。**

    ⚠ **别用 API 的 `q=<doi>&qmode=everything` 查重**（2026-09-05 实测栽过）：
    连着三次导入同一个 DOI，建出了三个条目。两个原因叠在一起 ——
    `q` 不是按字段精确匹配，而且它的索引**查不到刚写进去的东西**。
    查重要么准，要么就别叫查重：不准的查重比没有更糟，
    因为它会让人以为重复问题已经解决了。

    问云端不问本地：本地 API 反映的是桌面端已经同步下来的状态，滞后几分钟
    （踩坑 #64）。自己刚写上去的东西，只能问权威方。
    """
    from shared.adapters.zotero_client import _web
    out, start = {}, 0
    while True:
        batch = _web.zweb(f'/items/top?limit={int(limit)}&start={start}'
                          f'&format=json')
        if not batch:
            break
        for it in batch:
            d = it.get('data') or it
            doi = (d.get('DOI') or '').strip().lower()
            if doi and doi not in out:
                out[doi] = d.get('key')
        if len(batch) < limit:
            break
        start += limit
    return out


def ensure_tree(purpose, force=False):
    """确保「<顶层>/<用途>」这棵合集树在，返回用途那一层的 key。"""
    from shared.adapters.zotero_client import _web
    if purpose not in PURPOSES:
        raise ValueError(f'用途只能是 {list(PURPOSES)} 之一，给的是 {purpose!r}')
    sub, _ = PURPOSES[purpose]
    cols = _web.list_collections()          # 取一次，两步复用，少发一次请求
    top = _web.ensure_collection(collection_top(), None,
                                 action=f'建合集「{collection_top()}」',
                                 force=force, cols=cols)
    return _web.ensure_collection(sub, top,
                                  action=f'建合集「{collection_top()}/{sub}」',
                                  force=force, cols=cols)


def stash(doi, pdf_path, purpose='建库', col_key=None, index=None, force=False):
    """把一篇收进 Zotero → dict(doi, ok, action, item, note)。

    `action` 说明这次到底做了什么，四种：
      - `created`  新建了条目并挂了 PDF
      - `attached` 条目本来就有，只补了 PDF
      - `exists`   条目和 PDF 都已经有了，什么都没做
      - `failed`   出错了，note 里是原因

    **不打精读标签、不触发精读** —— 那是花钱的事，由用户自己决定什么时候开始。
    """
    from shared.adapters import crossref
    from shared.adapters.zotero_client import _web

    sub, _ = PURPOSES[purpose]
    out = {'doi': doi, 'ok': False, 'action': 'failed', 'item': '', 'note': ''}
    try:
        col_key = col_key or ensure_tree(purpose, force=force)
        # 整批共用一份索引：既省请求，也让**这一批里的重复**当场就被认出来
        if index is None:
            index = doi_index()
        key = index.get(doi.strip().lower())

        if not key:
            m = crossref.work(doi)
            item = crossref.to_zotero_item(
                m, tags=['来源/自动', f'用途/{purpose}'])
            item['collections'] = [col_key]
            r = _web.create_items([item], action=f'新建条目：{doi}', force=force)
            key = r['successful']['0']['key']
            index[doi.strip().lower()] = key    # 同一批后面再遇到就认得出来了
            out['action'] = 'created'
        else:
            _web.add_to_collection(key, col_key,
                                   action=f'把 {doi} 放进「{sub}」', force=force)
            out['action'] = 'exists'
        out['item'] = key

        # 挂 PDF。**已经有就不重复挂** —— 附件重复比条目重复更难收拾：
        # 条目重复还能合并，附件重复只能一个个删，而且删错了文件就没了。
        if not (pdf_path and os.path.exists(pdf_path)):
            out['note'] = '没有 PDF 可挂（只收了元数据）'
        elif _has_pdf_child(key):
            out['note'] = '已有 PDF 附件，没重复挂'
        else:
            att = _web.upload_attachment(key, pdf_path, 'Full Text PDF',
                                         action=f'给 {doi} 挂正文 PDF', force=force)
            # ⚠ **上传完必须再铺一份到本地 storage**，这不是优化（2026-09-05 踩过）。
            # 上传进的是 Zotero 官方存储，而用户的文件同步走 WebDAV（坚果云），
            # 桌面端只去 WebDAV 找 —— 于是条目有了、点开却是「找不到附件」。
            # 铺本地还顺带让 `find_pdf` 找得到，下游解析/精读才有正文可读。
            from shared.adapters import zotero_client as Z
            Z.put_local(att, pdf_path, os.path.basename(pdf_path))
            if out['action'] == 'exists':
                out['action'] = 'attached'

        out['ok'] = True
        log.info(f'{doi} → {out["action"]} {key}')
    except Exception as e:
        out['note'] = f'{type(e).__name__}: {e}'
        log.info(f'{doi} 收进库失败：{out["note"]}')
    return out


def _has_pdf_child(item_key):
    """这个条目下面已经有 PDF 附件了吗（问云端，理由同 find_by_doi）。"""
    from shared.adapters.zotero_client import _web
    try:
        kids = _web.zweb(f'/items/{item_key}/children?format=json')
    except Exception:
        return False
    for c in kids or []:
        d = c.get('data') or c
        if d.get('itemType') != 'attachment':
            continue
        if 'pdf' in (d.get('contentType') or '').lower():
            return True
    return False
