# -*- coding: utf-8 -*-
"""getpdf · 一批 DOI → 一批 PDF 落地（本工具的全部业务逻辑都在这个文件）

**解决的真实问题**：「把这几十篇的正文和 SI 弄到手」原来是人一篇篇点。
现在给 DOI 就行：借主力机上那个已登录的浏览器取件，落成本地正本并登记，之后落地流水线自动解析。

**它不负责的事**（都是刻意的）：
  - 怎么拿到 PDF → `shared.adapters.pdf_fetch`（借真实浏览器，见那块的 CLAUDE.md）
  - 元数据 → `shared.adapters.crossref`

**为什么默认慢**：出版商对短时间大量下载有风控，被掐的是**整个机构的 IP**，
不是某个账号 —— 代价由全校承担。所以 `GAP` 和 `LIMIT` 的默认值取保守值，
宁可慢，不可惹。想快的人得自己显式改，改的时候就会看见这段话。

对外接口：
  - probe()                       → 浏览器在不在 → dict
  - fetch_many(dois, ...)         → 逐篇取，返回每篇的结果 dict 列表
  - safe_name(doi)                → DOI → 能当文件名的样子
  - resolve_id(doi)               → 这篇在证据库里的 id（已有就用那个，没有按 DOI 生成）
  - land(doi, with_si)            → **收进证据库**：正文 + SI 落成本地正本，登记元数据

2026-10-13 起 Zotero 移出平台：原来的「推到 Zotero」（`stash` / `--to-zotero` / `attach_*` / `doi_index`）
和「从 Zotero 附件复制正本」都删了，旧代码在 git 标签 `zotero-before-removal`。
"""
import io
import os
import time

from shared.adapters import pdf_fetch, pdf_parse
from shared.kernel import catalog, paths
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

    oa = _try_open_access(doi, path)
    if oa:
        return oa
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


# `reason='oa'` 是本层加的（pdf_fetch.REASONS 只登记浏览器那条路的原因，它的自测会核对）
REASON_OA = '拿到了（合法的开放获取版本，没敲出版商）'


def _try_open_access(doi, path):
    """先问 Unpaywall 有没有合法的开放版本（2026-09-16）：有就直接下，**不碰出版商**。

    返回 fetch_one 形状的结果，或 None（没配邮箱 / 没有 / 下不到 → 走浏览器）。
    只收出版社正式版和接收稿；投稿稿（submittedVersion）内容可能和发表版不同，不要。
    """
    try:
        from shared.adapters import unpaywall
        data, info = unpaywall.fetch_pdf(doi)
    except Exception as e:
        log.info(f'{doi} 问 Unpaywall 没成：{str(e)[:60]}（改走浏览器）')
        return None
    if not data or (info or {}).get('version') == 'submittedVersion':
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'wb') as fh:
        fh.write(data)
    log.info(f'{doi} → {path}（开放获取 {info.get("version")}@{info.get("host")}，{len(data)} 字节，没敲出版商）')
    return {'doi': doi, 'ok': True, 'reason': 'oa', 'path': path, 'title': '',
            'landing': info.get('pdf_url', ''), 'bytes': len(data), 'oa_version': info.get('version')}


def fetch_pair(doi, where=None):
    """正文 + SI **一次落地**取回来 → (正文结果, SI 结果)，形状同 fetch_one / fetch_si_one。

    盘上已有的那半不再去取；两半都在就一次出版商都不敲。
    """
    where = where or out_dir(create=True)
    main = fetch_one(doi, where) if os.path.exists(
        os.path.join(where, safe_name(doi) + '.pdf')) else None
    si = None
    stem = safe_name(doi) + '_SI'
    for ext in ('.pdf', '.docx', '.doc', '.txt'):
        p = os.path.join(where, stem + ext)
        if os.path.exists(p) and os.path.getsize(p) > 1024:
            si = {'doi': doi, 'ok': True, 'reason': 'exists', 'path': p, 'bytes': os.path.getsize(p)}
    if main and si:
        return main, si
    if main and not si:
        return main, fetch_si_one(doi, where)
    if si and not main:
        return fetch_one(doi, where), si
    oa = _try_open_access(doi, os.path.join(where, safe_name(doi) + '.pdf'))
    if oa:
        return oa, fetch_si_one(doi, where)          # 正文不敲出版商了，SI 还得去（OA 版本一般不带 SI）

    rm, rs = pdf_fetch.fetch_both(doi)
    main = {'doi': doi, 'ok': False, 'reason': rm['reason'], 'path': '',
            'title': rm.get('title', ''), 'landing': rm.get('landing', ''), 'bytes': 0}
    if rm['ok']:
        path = os.path.join(where, safe_name(doi) + '.pdf')
        os.makedirs(where, exist_ok=True)
        with io.open(path, 'wb') as fh:
            fh.write(rm['pdf'])
        log.info(f'{doi} → {path}（{len(rm["pdf"])} 字节）')
        main.update(ok=True, reason='ok', path=path, bytes=len(rm['pdf']))
    else:
        log.info(f'{doi} 没拿到：{rm["reason"]}')
    si = {'doi': doi, 'ok': False, 'reason': rs['reason'], 'path': '', 'bytes': 0}
    if rs['ok']:
        ext = os.path.splitext(rs.get('filename') or '')[1].lower() or '.pdf'
        if ext not in ('.pdf', '.docx', '.doc', '.txt'):
            ext = '.pdf'
        ext = pdf_parse.real_ext(rs['pdf'], ext)      # 文件头说了算：Elsevier 的 mmc1.docx 常常是 PDF
        path = os.path.join(where, stem + ext)
        with io.open(path, 'wb') as fh:
            fh.write(rs['pdf'])
        log.info(f'{doi} 的 SI → {path}（{len(rs["pdf"])} 字节）')
        si.update(ok=True, reason='ok', path=path, bytes=len(rs['pdf']))
    else:
        log.info(f'{doi} 的 SI 没拿到：{rs["reason"]}')
    return main, si


def fetch_many(dois, where=None, gap=GAP, limit=LIMIT, on_each=None):
    """逐篇取。返回结果列表。

    **撞上人机验证就停**，不是跳过 —— 验证码是「人去点一下，然后整批都会顺」，
    继续硬跑只会把剩下的全废掉，还多敲了出版商一堆次。
    """
    todo = [d.strip() for d in dois if pdf_fetch.is_doi(d.strip())][:limit]
    where = where or out_dir(create=True)
    results = []
    from shared.kernel import heartbeat
    for i, doi in enumerate(todo):
        r = fetch_one(doi, where)
        results.append(r)
        heartbeat.progress('getpdf')       # 面板上看得见「取件多久没动了」
        if on_each:
            on_each(i + 1, len(todo), r)
        if r['reason'] == 'captcha':
            log.info('撞上人机验证，停在这里等人去点')
            break
        # 最后一篇后面不用等；从盘上直接命中的也不用等（没敲出版商）
        if i + 1 < len(todo) and r['reason'] != 'exists':
            time.sleep(gap)
    heartbeat.done('getpdf')
    return results


def summarize(results):
    """一批结果 → 按 reason 分组的计数，给人看的。"""
    counts = {}
    for r in results:
        counts[r['reason']] = counts.get(r['reason'], 0) + 1
    return counts


# ── 收进证据库（本地正本）────────────────────────────────────────────────
# 正本在 raw/<id>/，目录在 curated/<id>/meta.json。

def resolve_id(doi):
    """DOI → 这篇在本平台的 id：证据库里已经有 → 用那个 id（不管它长什么样），别另起一份；
    没有 → 按 DOI 生成（`paths.paper_id_from_doi`）。"""
    d = catalog.norm_doi(doi)
    return catalog.find(d) or paths.paper_id_from_doi(d)


def _copy(src, dst):
    """把文件收成正本（已经在就不动）。返回是否真收了。

    来源在临时处理区（`paths.INCOMING`）的**搬**而不是复制 —— 2026-09-15 量过主力机：
    `_incoming` 里躺着 12 GB 早已落地的副本，占了 raw 的三成。别处来的（Zotero 附件、
    调用方给的文件）仍然复制，那不是我们的东西。
    """
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.abspath(src).startswith(os.path.abspath(paths.INCOMING)):
        try:
            os.replace(src, dst)
            return True
        except OSError:
            pass                              # 跨盘等情况退回复制
    with io.open(src, 'rb') as a, io.open(dst, 'wb') as b:
        b.write(a.read())
    return True


def _register_meta(pid, doi, source):
    """登记元数据：标题 / 年份 / 期刊 / 作者从 Crossref 取。**只补不覆盖**，取不到就只记 DOI。"""
    have = catalog.read_meta(pid)
    fields = {'doi': doi, 'source': source}
    if not have.get('title'):
        try:
            from shared.adapters import crossref
            it = crossref.to_zotero_item(crossref.work(doi))
            names = [(c.get('lastName') or '') + ' ' + (c.get('firstName') or '')
                     for c in (it.get('creators') or [])]
            fields.update(title=it.get('title'), journal=it.get('publicationTitle'),
                          year=(it.get('date') or '')[:4],
                          authors=[n.strip() for n in names if n.strip()][:20])
        except Exception as e:
            log.info(f'{doi} 取元数据没成（不影响落地）：{type(e).__name__}: {e}')
    return catalog.register(pid, **fields)


def land(doi, with_si=True, allow_fetch=True, pdf_path=None, si_path=None):
    """把一篇**收进证据库** → dict(doi, id, ok, action, source, pdf, si, note)。

    正文从哪来（按顺序，拿到就停）：本地正本已有 → 调用方给的文件 → 借浏览器向出版商取。
    SI 同理。最后登记 meta.json。**幂等**：跑两遍 = 跑一遍。

    `action`：`landed` 这次真落了新东西 / `exists` 早就齐了 / `failed` 连正文都没有。
    `allow_fetch=False` 时不向出版商发任何请求（「先看看手上有没有」）。
    """
    doi = catalog.norm_doi(doi)
    out = {'doi': doi, 'id': '', 'ok': False, 'action': 'failed', 'source': '',
           'pdf': '', 'si': '', 'note': '', 'reason': ''}
    if not pdf_fetch.is_doi(doi):
        out['note'] = '不像一个 DOI'
        return out
    try:
        pid = resolve_id(doi)
    except paths.BadKeyError as e:
        out['note'] = str(e)
        return out
    out.update(id=pid)
    changed = False
    fetched_si = None                 # fetch_pair 顺手取回的 SI（下面 SI 那段先认它）

    # ── 正文 ──
    main = paths.local_pdf(pid)
    if os.path.exists(main) and os.path.getsize(main) > 0:
        out['source'] = catalog.SRC_LOCAL
    elif pdf_path and os.path.exists(pdf_path):
        changed |= _copy(pdf_path, main)
        out['source'] = catalog.SRC_LOCAL
    else:
        if allow_fetch:
            # 正文和 SI 都要取的话一次落地一起取（`fetch_pair`）：同一个页面不开两遍
            si_needed = with_si and not paths.find_local_si(pid) and not (si_path and os.path.exists(si_path))
            if si_needed:
                r, fetched_si = fetch_pair(doi)
            else:
                r = fetch_one(doi)
            out['reason'] = r['reason']          # 机器读的失败原因 / 'oa' / 'ok'（状态码与 route 靠它）
            if r['ok']:
                changed |= _copy(r['path'], main)
                out['source'] = catalog.SRC_FETCH
            else:
                out['note'] = '正文没取到 —— ' + pdf_fetch.REASONS.get(r['reason'], r['reason'])
        else:
            out['note'] = '手上没有正文，而且这次不允许去取'
    if os.path.exists(main):
        out['pdf'] = main

    # ── SI ──
    if with_si:
        have = paths.find_local_si(pid)
        if have:
            out['si'] = have
        else:
            src = si_path if (si_path and os.path.exists(si_path)) else ''
            si_r = None
            if not src and fetched_si is not None:
                si_r = fetched_si
                src = fetched_si['path'] if fetched_si['ok'] else ''
            elif not src and allow_fetch and out['pdf']:
                si_r = fetch_si_one(doi)
                src = si_r['path'] if si_r['ok'] else ''
            if si_r and not si_r['ok']:
                out['si_reason'] = si_r.get('reason', '')
            if si_r and not si_r['ok'] and si_r.get('reason') == 'no_si':
                # 出版商页面确认没挂 SI（综述、老文献常见）：记下来，以后别再敲它
                catalog.mark_si_none(pid, pdf_fetch.REASONS['no_si'])
                out['note'] = (out['note'] + '；' if out['note'] else '') + '没有 SI（出版商页面确认）'
            if src:
                ext = pdf_parse.real_ext(src, os.path.splitext(src)[1].lower()).lstrip('.')
                dst = paths.local_si(pid, ext if ext in ('pdf', 'docx') else 'pdf')
                changed |= _copy(src, dst)
                out['si'] = dst

    # ── 登记 ──
    if out['pdf'] or out['si']:
        _register_meta(pid, doi, out['source'] or catalog.SRC_LOCAL)
    out['ok'] = bool(out['pdf'])
    out['action'] = ('landed' if changed else 'exists') if out['ok'] else 'failed'
    log.info(f'{doi} → {pid} {out["action"]}（{out["source"]}）')
    return out


def land_file(pid, pdf_path, **meta):
    """没有 DOI 的一篇：给定 id（如 `paths.paper_id_from_cnki`）+ 本地 PDF → 收成正本并登记 → dict(id, ok, action, pdf)。

    `land` 认 DOI（跨来源认同一篇靠它）；这条只给真没有 DOI 的（知网上一部分中文期刊文章）。**幂等**。
    """
    pid = paths.check_key(pid)
    out = {'id': pid, 'ok': False, 'action': 'failed', 'pdf': ''}
    if not (pdf_path and os.path.exists(pdf_path)):
        return out
    main = paths.local_pdf(pid)
    changed = _copy(pdf_path, main)
    catalog.register(pid, source=catalog.SRC_LOCAL, **meta)
    out.update(ok=True, action='landed' if changed else 'exists', pdf=main)
    log.info(f'{pid} {out["action"]}（无 DOI，本地文件）')
    return out


def si_todo():
    """该补 SI 的清单：有正文、有 DOI、SI 状态是「没取过」（不含出版商确认没有的）。零网络。"""
    out = []
    for pid in catalog.ids():
        r = catalog.record(pid)
        if r['pdf'] and r['doi'] and not r['si'] and catalog.si_status(pid) == catalog.SI_UNKNOWN:
            out.append((pid, r['doi']))
    return out


def fill_si(gap=GAP, limit=None, log=print):
    """给证据库里「没取过 SI」的文献补 SI（2026-09-17 用户要求）。→ Counter(拿到 / 确认没有 / 没成 / 人机验证)。

    幂等、可断点：每篇结果当场登记（拿到 → si.*；出版商说没挂 → si_status=none），中途停了再跑只做剩下的。
    节奏按 `GAP`（默认 20 秒），撞上人机验证**就停**（人去那个浏览器点一下再跑）—— 出版商掐的是全校的 IP。
    """
    from collections import Counter
    todo = si_todo()
    if limit:
        todo = todo[:limit]
    c = Counter()
    log(f'该补 SI 的 {len(todo)} 篇，每篇间隔 {gap} 秒，预计 {len(todo) * (gap + 8) // 60} 分钟')
    for i, (pid, doi) in enumerate(todo, 1):
        r = land(doi, pdf_path=paths.local_pdf(pid))
        if r.get('si_reason') == 'navigate_failed':
            # 页面根本没打开（多半是 ERR_CONNECTION_CLOSED 这种一过性的网络抖动）：歇一下再来一次
            log(f'  [{i}/{len(todo)}] 页面没打开，{gap} 秒后重试一次  {doi}')
            time.sleep(gap)
            r = land(doi, pdf_path=paths.local_pdf(pid))
        if r.get('si'):
            c['拿到'] += 1; mark = '✓ 拿到'
        elif catalog.si_status(pid) == catalog.SI_NONE:
            c['确认没有'] += 1; mark = '— 出版商没挂'
        elif '人机验证' in (r.get('note') or ''):
            c['人机验证'] += 1
            log(f'  [{i}/{len(todo)}] {doi}  撞上人机验证，停在这里 —— 去「取全文用的浏览器」点一下，再跑一次接着补')
            break
        else:
            c['没成'] += 1; mark = '× ' + (r.get('note') or '没取到')
        log(f'  [{i}/{len(todo)}] {mark}  {doi}')
        if i < len(todo):
            time.sleep(gap)
    log(f'补 SI 结束：拿到 {c["拿到"]} · 确认没有 {c["确认没有"]} · 没成 {c["没成"]}'
        + ('（撞人机验证停下）' if c['人机验证'] else ''))
    return c


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
    ext = pdf_parse.real_ext(r['pdf'], ext)           # 文件头说了算
    path = os.path.join(where, stem + ext)
    os.makedirs(where, exist_ok=True)
    with io.open(path, 'wb') as fh:
        fh.write(r['pdf'])
    log.info(f'{doi} 的 SI → {path}（{len(r["pdf"])} 字节）')
    return {'doi': doi, 'ok': True, 'reason': 'ok', 'path': path,
            'bytes': len(r['pdf'])}
