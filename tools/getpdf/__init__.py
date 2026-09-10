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
    """PDF 落在哪：临时处理区。**不写死路径**（强制规范 #4）。"""
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

# 合集名字走 config，用户可以在控制面板改，改了不用动代码（强制规范 #3）。
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


def resolve_collection(spec, force=False):
    """把「阿课题/抗冲丙烯酸酯」这样的路径（或一个 8 位 key）解析成合集 key。

    **为什么要有它**（2026-09-10）：`stash` 原来只会把条目归进固定的
    「<顶层>/建库用」。用户说「收进阿课题下的某某文件夹」时，外部 agent 没有入口，
    于是自己去调底层接口 —— 失败之后**给失败编了一套「跨账号安全隔离」的解释**，
    而那个机制根本不存在。缺入口的代价不只是干不成，还有一份听起来很合理的假汇报。

    规矩（刻意的）：
      · **中间层必须已经存在**，不存在就报错并列出那一层实际有什么 ——
        让调用方照着改，而不是让它自由发挥
      · **只有最后一层允许新建**（用户说「建个子文件夹」指的就是这一层）
      · 传 8 位 key 就直接用它，不做路径解析
    """
    from shared.adapters.zotero_client import _web
    spec = (spec or '').strip().strip('/')
    if not spec:
        return None
    cols = _web.list_collections()
    by_key = {c['key']: c for c in cols}
    if spec in by_key:                       # 直接给了 key
        return spec

    parent, walked = None, []
    parts = [p.strip() for p in spec.split('/') if p.strip()]
    for i, name in enumerate(parts):
        last = (i == len(parts) - 1)
        hit = _web.find_collection(name, parent, cols=cols)
        if hit:
            parent, walked = hit, walked + [name]
            continue
        if not last:
             # 中间层缺失 —— 把这一层真实有什么列出来，比一句「找不到」有用得多
            siblings = sorted(c['data']['name'] for c in cols
                              if (c['data'].get('parentCollection') or None) == parent)
            where = '/'.join(walked) or '（顶层）'
            raise ValueError(
                f'合集路径「{spec}」里的「{name}」不存在。'
                f'{where} 下面现有：{("、".join(siblings[:12]) or "（空）")}'
                f'{"…" if len(siblings) > 12 else ""}。'
                f'**只有最后一层允许新建**，中间层请用真实存在的名字。')
        parent = _web.ensure_collection(name, parent,
                                        action=f'建合集「{spec}」', force=force, cols=cols)
        walked.append(name)
    return parent


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


def stash(doi, pdf_path, purpose='建库', col_key=None, index=None, force=False,
          collection=None):
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
    out = {'doi': doi, 'ok': False, 'action': 'failed', 'item': '', 'note': '',
           'collection': ''}
    try:
        # `collection` 给了就归到那里，**取代**默认的「<顶层>/建库用」——
        # 用户说「收进某某文件夹」时要的就是这个。那棵默认树只是组织用的，
        # 没有任何下游在读它（查过：只有公众号导入的提示语提了一句）。
        if collection:
            col_key = resolve_collection(collection, force=force)
            sub = collection
        col_key = col_key or ensure_tree(purpose, force=force)
        out['collection'] = sub
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
            # ⚠ 条目**不是本流水线建的**时候，它身上不会有平台约定的那两个标签，
            #   摘要也可能是空的 —— 于是它对下游整个隐形：`curate` 认不出来源，
            #   粗层向量化没有可检索的内容。2026-09-09 真实发生过：
            #   外部 agent 绕过本函数、直接调 `create_items` 建了三条，
            #   元数据（DOI/期刊/作者）都对，唯独缺标签和摘要。
            #   所以这条分支要**补齐**，而不是只把它放进合集就完事。
            _backfill(key, doi, purpose, force=force)
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


def _backfill(item_key, doi, purpose, force=False):
    """把库里已有条目缺的那几样补上：平台标签 + 空摘要。**只补，绝不覆盖。**

    只在两种东西缺失时才动手，且只动这两样：
      · 平台约定的标签 `来源/自动` 与 `用途/<purpose>` —— 缺哪个补哪个
      · `abstractNote` **为空**时才去 Crossref 取一份填上

    为什么不覆盖已有内容：用户可能手工改过标题、加过自己的标签、写过笔记。
    「补齐」和「以我为准」是两件事，这里只做前者。

    补不上不算失败（Crossref 查不到、网络不通都可能），静默跳过 ——
    调用方要的是 PDF 挂上去，元数据是顺带的。
    """
    from shared.adapters import crossref
    from shared.adapters.zotero_client import _web
    want = {'来源/自动', f'用途/{purpose}'}
    try:
        cur = _web.get_item(item_key)
        d = cur.get('data') or {}
        have = {t.get('tag') for t in (d.get('tags') or [])}
        patch = {}
        if not want.issubset(have):
            patch['tags'] = [{'tag': t} for t in sorted(have | want) if t]
        if not (d.get('abstractNote') or '').strip():
            m = crossref.work(doi)
            ab = (crossref.to_zotero_item(m).get('abstractNote') or '').strip()
            if ab:
                patch['abstractNote'] = ab
        if patch:
            _web.patch_item(item_key, patch,
                            action=f'补齐 {doi} 的标签/摘要（只补空的，不覆盖）',
                            force=force)
            log.info(f'{doi} 补齐了：{"、".join(patch)}')
    except Exception as e:
        log.info(f'{doi} 补齐元数据没成（不影响挂 PDF）：{type(e).__name__}: {e}')


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


def fetch_si_one(doi, where=None):
    """取一篇的补充材料 → dict(doi, ok, reason, path, bytes)。

    只要**实验那份**，视频一律不要（挑法见 `pdf_fetch.pick_si`）。
    已经在盘上的直接跳过，跟正文一个道理。

    为什么值得取：本项目 2026-07-25 验证过 ——
    **投料量、配比、温度时间几乎只写在 SI 里**。
    只灌正文的话，向量库里搜「硼酸配比多少」是搜不出数的。
    """
    where = where or out_dir(create=True)
    stem = safe_name(doi) + '_SI'
    for ext in ('.pdf', '.docx', '.doc', '.txt'):
        p = os.path.join(where, stem + ext)
        if os.path.exists(p) and os.path.getsize(p) > 1024:
            return {'doi': doi, 'ok': True, 'reason': 'exists', 'path': p,
                    'bytes': os.path.getsize(p)}

    r = pdf_fetch.fetch(doi, kind='si')
    if not r['ok']:
        log.info(f'{doi} 的 SI 没拿到：{r["reason"]}')
        return {'doi': doi, 'ok': False, 'reason': r['reason'], 'path': '',
                'bytes': 0}

    ext = os.path.splitext(r.get('filename') or '')[1].lower() or '.pdf'
    if ext not in ('.pdf', '.docx', '.doc', '.txt'):
        ext = '.pdf'
    path = os.path.join(where, stem + ext)
    os.makedirs(where, exist_ok=True)
    with io.open(path, 'wb') as fh:
        fh.write(r['pdf'])
    log.info(f'{doi} 的 SI → {path}（{len(r["pdf"])} 字节）')
    return {'doi': doi, 'ok': True, 'reason': 'ok', 'path': path,
            'bytes': len(r['pdf'])}


def attach_pdf(item_key, pdf_path, force=False):
    """把正文 PDF 挂到已有条目下 → (做了没, 说明)。

    `stash()` 建条目时顺手就挂了，所以这个函数是给**另一条路**用的：
    文献先落在本地（`paths.local_pdf`），过些天才决定要传进 Zotero
    （2026-09-06 加，用户定的「先下到本地，需要的再传」）。
    """
    from shared.adapters import zotero_client as Z
    from shared.adapters.zotero_client import _web
    if not (pdf_path and os.path.exists(pdf_path)):
        return False, '没有 PDF 文件可挂'
    if _has_pdf_child(item_key):
        return False, '已有 PDF 附件，没重复挂'
    att = _web.upload_attachment(item_key, pdf_path, 'Full Text PDF',
                                 action='挂正文 PDF', force=force)
    Z.put_local(att, pdf_path, os.path.basename(pdf_path))
    return True, ''


def attach_si(item_key, si_path, force=False):
    """把 SI 挂到已有条目下 → (做了没, 说明)。

    附件标题固定用 **`SI`** —— 跟库里已有的 32 篇一致，
    而且 `deepread` 找 SI 就是认这个名字。改名等于让精读线找不到它。
    """
    from shared.adapters import zotero_client as Z
    from shared.adapters.zotero_client import _web
    if not (si_path and os.path.exists(si_path)):
        return False, '没有 SI 文件可挂'
    for c in (_web.zweb(f'/items/{item_key}/children?format=json') or []):
        d = c.get('data') or c
        if d.get('itemType') == 'attachment' and (d.get('title') or '').strip().upper() == 'SI':
            return False, '已有 SI 附件，没重复挂'
    att = _web.upload_attachment(item_key, si_path, 'SI',
                                 action='挂补充材料（SI）', force=force)
    # 跟正文一样，**上传完必须铺一份到本地**（踩坑 #120），否则用户点开是「找不到附件」
    Z.put_local(att, si_path, os.path.basename(si_path))
    return True, ''
