# -*- coding: utf-8 -*-
"""fulltext · 一个 DOI → **LLM 读得懂的全文**。四层回退，全程计时。

## 这是整条路上缺的那一环

通用 LLM 拿不到付费墙后面的东西 —— 它能搜到的只有摘要和开放获取。
而这台机器有三样它没有的：机构订阅权限（靠出口 IP）、一个过过人机验证的
真实浏览器、MineRU 解析额度。**把这三样接到模型手上，付费墙就跨过去了。**

## 四层回退（越靠前越快越省）

    1. 缓存      `raw/<id>/parsed/full.md` 已经在      → 秒回，零成本
    2. 本地正本  `raw/<id>/main.pdf` 已经在            → 只解析
    3. Zotero    库里这篇有 PDF 附件                    → **复制成本地正本**，再解析
    4. 取        借浏览器向出版商要                      → 20 秒间隔，慢是故意的

2～4 层都归 `getpdf.land()` 做（2026-09-13 起）：不管从哪来，**正本一律落进 raw/<id>/
并登记进证据库目录**，本模块只负责解析。

## 职责边界（**别在这里读全文**）

本模块只负责「**把料弄进来**」，返回一个可用的 id。
「读」是 `tools/library` 的事（`outline` 看菜单、`section` 按地址取原文）——
两个工具零耦合，各自只依赖 adapters 与 shared，不互相 import（硬规则 2）。

**为什么不直接返回全文**：一篇平均 5 万字符 ≈ 1.3 万 token，模型读三篇就把
上下文吃掉一半，而一个问题真正要看的往往是两三节。先给菜单再点菜，
成本大约是整篇的三十分之一（实测菜单是全文的 2.0%）。

## 计时是刻意的

每一步都记进 `runs` 表（`shared.kernel.jobs`）。2026-09-08 想估「一次问答
要等多久」时才发现：**取 PDF 这一步从来没有记过时间**，只能拿 20 秒的设计值推算。
从这版起，取和解析的真实耗时都会攒下来。
"""
import io
import os
import sys
import time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.adapters import pdf_fetch, pdf_parse
from shared.kernel import jobs, paths
from shared.kernel.log import get_logger

log = get_logger('getpdf')

# 来源标签：给模型看的「这篇是怎么来的」，也用来解释为什么快/慢
SRC_CACHE = 'cache'        # 解析过了，秒回
SRC_LOCAL = 'local'        # 本地有 PDF，只花解析
SRC_ZOTERO = 'zotero'      # Zotero 库里有附件，只花解析
SRC_FETCH = 'fetch'        # 真去出版商取了


def resolve_id(doi, zotero_index=None):
    """DOI → 这篇在本平台的 id。实现在 `getpdf.resolve_id`（证据库 → Zotero → 按 DOI 生成）。"""
    from tools import getpdf
    return getpdf.resolve_id(doi, zotero_index)


def _parse(pid, pdf_path):
    """PDF → `parsed/full.md`。记时、记账。返回 (成功, 秒, 说明)。"""
    out = paths.parsed_dir(pid, create=True)
    t0 = time.time()
    run = jobs.start(pid, 'parse', producer='fulltext')
    try:
        pdf_parse.parse_pdf(pdf_path, out, reuse=True)
    except Exception as e:                    # 解析失败不该炸掉整批
        jobs.fail(run, str(e)[:200])
        return False, time.time() - t0, '解析失败：%s' % str(e)[:120]
    jobs.finish(run)
    ok = os.path.exists(paths.fulltext(pid))
    return ok, time.time() - t0, '' if ok else '解析跑完了但没产出 full.md'


def one(doi, zotero_index=None, allow_fetch=True):
    """一篇 → dict(doi, id, ok, source, secs, chars, why)。**不抛异常**。

    `allow_fetch=False` 时只走前三层（不向出版商发任何请求）——
    「先看看手上有没有」这种问法不该触发一次真实下载。
    """
    t0 = time.time()
    doi = (doi or '').strip()
    if not pdf_fetch.is_doi(doi):
        return {'doi': doi, 'id': '', 'ok': False, 'source': '', 'secs': 0,
                'chars': 0, 'why': '不像一个 DOI（应形如 10.1016/j.cej.2025.164092）'}
    try:
        pid, in_zotero = resolve_id(doi, zotero_index)
    except paths.BadKeyError as e:
        return {'doi': doi, 'id': '', 'ok': False, 'source': '', 'secs': 0,
                'chars': 0, 'why': str(e)}

    def done(ok, source, why=''):
        chars = 0
        if ok:
            try:
                chars = os.path.getsize(paths.fulltext(pid))
            except OSError:
                chars = 0
        return {'doi': doi, 'id': pid, 'ok': ok, 'source': source,
                'secs': round(time.time() - t0, 1), 'chars': chars,
                'in_zotero': in_zotero, 'why': why,
                'si': _si_state(pid, allow_fetch) if ok else ''}

    # ── 1. 缓存 ────────────────────────────────────────────────────
    if os.path.exists(paths.fulltext(pid)):
        # 正文早就有、SI 还缺（上次没取成）：趁这次有人要这篇，去补 SI。
        # 出版商确认过没挂的（si_status=none）不再去敲（2026-09-30：Angew 一篇正文在、SI 一直缺）
        from shared.kernel import catalog
        if allow_fetch and catalog.si_status(pid) == catalog.SI_UNKNOWN:
            _land(doi, allow_fetch, zotero_index)
        return done(True, SRC_CACHE)

    # ── 2～4. 落成本地正本（本地 → Zotero 复制 → 真去取）───────────
    had_local = os.path.exists(paths.local_pdf(pid))
    run = None if had_local else jobs.start(pid, 'fetch', producer='fulltext')
    landed = _land(doi, allow_fetch, zotero_index)
    if not landed['ok']:
        if run:
            jobs.fail(run, landed.get('note') or 'no_pdf')
        return done(False, SRC_FETCH if allow_fetch else '',
                    landed.get('note') or '没取到')
    if run:
        jobs.finish(run)
    source = {'local': SRC_LOCAL, 'zotero': SRC_ZOTERO, 'fetch': SRC_FETCH}.get(
        landed.get('source'), SRC_LOCAL)
    ok, _s, why = _parse(pid, landed['pdf'])
    return done(ok, source, why)


def _si_state(pid, allow_parse=True):
    """这篇的 SI 到哪一步了；原件在、还没解析就**顺手解析**（2026-09-30）。

    → 'parsed' / 'none'（没有 SI 原件）/ 'failed:<why>' / 'unparsed'（只查不取时不解析）。

    为什么在这里做：SI 解析原来只由落地流水线（host.ingest）做，而那条线 09-27 起随「后台自动建库」停了 ——
    Claude Science 取了两篇，si.pdf 都在盘上，却一篇都没解析，它看不到软件、力场、泛函这些只写在 SI 里的细节。
    取全文是有人明确要这篇，SI 就该一起备好。pdf 走 MineRU（花解析额度，不花模型钱），docx 直接读字。
    """
    if os.path.exists(paths.si_fulltext(pid)):
        return 'parsed'
    src = paths.find_local_si(pid)
    if not src:
        return 'none'
    if not allow_parse:
        return 'unparsed'
    run = jobs.start(pid, 'parse_si', producer='fulltext')
    try:
        pdf_parse.parse_document(src, paths.si_parsed_dir(pid, create=True), reuse=True)
    except Exception as e:
        jobs.fail(run, str(e)[:200])
        return 'failed:%s' % str(e)[:80]
    jobs.finish(run)
    return 'parsed' if os.path.exists(paths.si_fulltext(pid)) else 'failed:没产出 full.md'


def _land(doi, allow_fetch, zotero_index):
    """真正去落地。**单独一个函数是为了能在测试里替换掉**（别真敲出版商）。"""
    from tools import getpdf
    return getpdf.land(doi, with_si=True, allow_fetch=allow_fetch,
                       zotero_index=zotero_index)


def many(dois, allow_fetch=True, gap=None, progress=None, limit=3):
    """一批 DOI → 一批结果。**取是串行的，20 秒间隔不能省**。

    为什么默认只收 3 篇（`limit`）：出版商风控封的是**整个机构的 IP**，
    而模型不知道这个代价有多重。真要一整批，走 `getpdf_batch` 那条人点的路。

    `progress` 给一个文件路径就会边跑边写进度 —— 这是「发起 + 轮询」的那半。
    """
    from tools import getpdf
    dois = [d.strip() for d in (dois or []) if d and d.strip()][:max(1, int(limit))]
    gap = getpdf.GAP if gap is None else gap
    index = {}
    # Zotero 的 DOI 索引要问一趟 Zotero（实测约 10 秒）。全都已经在证据库里、解析过的，
    # 根本用不上它 —— 「只查不取」原来 11.5 秒、而 library_db_search 只要 1 秒，就差在这（2026-09-30）
    from shared.kernel import catalog
    def _cached(d):
        pid = catalog.find(d)
        return bool(pid) and os.path.exists(paths.fulltext(pid))
    if not all(_cached(d) for d in dois):
        try:
            index = getpdf.doi_index()         # Zotero 里已有的先认出来，能省一次下载
        except Exception as e:
            log.warn('取 Zotero 的 DOI 索引失败（不影响，只是可能重下）：%s', str(e)[:120])

    out, t0 = [], time.time()
    for i, doi in enumerate(dois):
        r = one(doi, zotero_index=index, allow_fetch=allow_fetch)
        out.append(r)
        _write_progress(progress, dois, out, t0, done=False)
        # 只有**真去取了**才需要礼貌间隔；命中缓存/本地的不算敲出版商
        if (r.get('source') == SRC_FETCH and i + 1 < len(dois) and gap > 0):
            time.sleep(gap)
    # 撞上人机验证 / 被挡回验证页的，歇一会儿**补试一次**（2026-09-30：RSC 的 Cloudflare 时有时无，
    # 同一篇隔几分钟再取就过了）。仍然串行、每篇之间照样隔 gap；只补试一次，不死磕。
    again = [i for i, r in enumerate(out) if allow_fetch and blocked(r)]
    if again:
        log.info('%d 篇撞上人机验证，歇 %d 秒后补试一次', len(again), RETRY_COOLDOWN)
        time.sleep(RETRY_COOLDOWN)
        for n, i in enumerate(again):
            out[i] = one(dois[i], zotero_index=index, allow_fetch=True)
            _write_progress(progress, dois, out, t0, done=False)
            if n + 1 < len(again) and gap > 0:
                time.sleep(gap)
    _write_progress(progress, dois, out, t0, done=True)
    return out


RETRY_COOLDOWN = 60        # 撞上人机验证的，整批跑完后歇多久再补试一次


def blocked(r):
    """这篇是不是被人机验证 / 验证页挡住的（值得过一会儿再试，而不是没权限、没链接）。"""
    why = r.get('why') or ''
    return (not r.get('ok')) and any(pdf_fetch.REASONS[k] in why for k in ('captcha', 'not_pdf'))


def _write_progress(path, dois, results, t0, done):
    if not path:
        return
    import json
    payload = {'total': len(dois), 'finished': len(results), 'done': done,
               'elapsed': round(time.time() - t0, 1), 'results': results}
    try:
        io.open(path, 'w', encoding='utf-8').write(
            json.dumps(payload, ensure_ascii=False, indent=1))
    except OSError:
        pass                                   # 写不下进度不该让作业本身失败


def summarize(results):
    """一批结果 → 给模型看的文本。**每篇都说清楚是怎么来的、花了多久**。"""
    if not results:
        return '没有可处理的 DOI。'
    lines, by = [], {}
    for r in results:
        by[r.get('source') or '失败'] = by.get(r.get('source') or '失败', 0) + 1
        if r['ok']:
            lines.append('✓ %s → %s（%s，%.0fs，%d 字符）'
                         % (r['doi'], r['id'], _cn(r['source']), r['secs'], r['chars']))
        else:
            lines.append('✗ %s —— %s' % (r['doi'], r['why']))
    ok = [r for r in results if r['ok']]
    tail = ''
    if ok:
        # 2026-09-14：做完直接把菜单带回来，模型少一次调用。骨架是纯脚本、几十毫秒；
        # 不 import tools.library（工具隔离），直接用 shared.domain.schema.outline。
        menus = [_menu_of(r['id']) for r in ok]
        tail = ('\n\n菜单（按地址用 library_section 取节 / 段 / 表，别一口气读全文）：\n'
                + '\n\n'.join(menus))
    return '\n'.join(lines) + tail


def _menu_of(pid):
    """这篇的骨架菜单文本。有缓存用缓存（落地流水线 / library 都会写），没有就现算。"""
    import json
    from shared.domain.schema import outline as _outline
    try:
        cache = paths.outline(pid)
        si_p = paths.si_fulltext(pid)
        md = io.open(paths.fulltext(pid), encoding='utf-8').read()
        si_md = io.open(si_p, encoding='utf-8').read() if os.path.exists(si_p) else ''
        o = json.load(io.open(cache, encoding='utf-8')) if os.path.exists(cache) else {}
        if not _outline.is_current(o, md, si_md):       # 签名对不上 = 旧缓存，现算
            o = _outline.build_outline(md, si_md=si_md)
        body = _outline.menu(o)
        if o.get('si'):
            body += '\n--- 补充材料 SI ---\n' + _outline.menu(o['si'])
        return '%s · 全文 %d 字符\n%s' % (pid, (o.get('stats') or {}).get('chars', 0), body)
    except Exception as e:
        return '%s：菜单暂时取不到（%s），用 library_outline 再看一次' % (pid, type(e).__name__)


def _cn(source):
    return {SRC_CACHE: '早就解析过', SRC_LOCAL: '本地有 PDF',
            SRC_ZOTERO: 'Zotero 库里有', SRC_FETCH: '刚去取的'}.get(source, source)
