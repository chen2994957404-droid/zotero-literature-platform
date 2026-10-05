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

## 解析分两层（2026-10-04，Claude Science 的需求文档 P0-1）

PDF 一到手先出**快速文本层**（PyMuPDF，本地几秒，`tier=text`），马上能按节按段读；
MineRU 交给后台的 `Upgrader` 慢慢等，成功了升级成 `tier=structured`（表格、图），
失败了快速层照旧可用。起因：2026-10-02 两篇 PDF 都在盘上，MineRU 一直 pending，
15 分钟超时后 chars=0，调用方什么也读不到，整条队列还跟着停。

## 结果带机器读的状态码

`code`（OK / CAPTCHA_REQUIRED / NOT_SUBSCRIBED / NOT_FOUND / NO_PDF_LINK / PARSE_PENDING /
PARSE_FAILED / NETWORK_ERROR / NOT_FETCHED）+ `retryable` + `stage` + `tier` + `route`；中文 `why` 照留。

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
import threading
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

# ── 结果里给机器读的状态码（2026-10-04，Claude Science 的需求文档 P0-2）─────────
# 中文 `why` 照留（给人看）；调用方按 `code` 分支、按 `retryable` 决定要不要再交一次。
OK = 'OK'
CAPTCHA_REQUIRED = 'CAPTCHA_REQUIRED'   # 撞上人机验证 / 被挡回验证页：人去取全文用的浏览器点一下，再续跑
NOT_SUBSCRIBED = 'NOT_SUBSCRIBED'       # 页面在、学校没订
NOT_FOUND = 'NOT_FOUND'                 # DOI 无效 / 出版商页面打不开
NO_PDF_LINK = 'NO_PDF_LINK'             # 页面在、像有权限，但找不到 PDF 链接（出版商改版）
PARSE_PENDING = 'PARSE_PENDING'         # PDF 在手，可读文本还没出来（扫描件等 MineRU 的 OCR）
PARSE_FAILED = 'PARSE_FAILED'
NETWORK_ERROR = 'NETWORK_ERROR'         # 浏览器没开 / 网络断 / 超时 —— 可重试
NOT_FETCHED = 'NOT_FETCHED'             # 只查不取：手上没有，这次也没去取
CODES = (OK, CAPTCHA_REQUIRED, NOT_SUBSCRIBED, NOT_FOUND, NO_PDF_LINK, PARSE_PENDING,
         PARSE_FAILED, NETWORK_ERROR, NOT_FETCHED)

_REASON_CODE = {'captcha': CAPTCHA_REQUIRED, 'not_pdf': CAPTCHA_REQUIRED, 'no_access': NOT_SUBSCRIBED,
                'no_pdf_link': NO_PDF_LINK, 'navigate_failed': NOT_FOUND, 'too_big': NETWORK_ERROR}
RETRYABLE = {CAPTCHA_REQUIRED, PARSE_PENDING, NETWORK_ERROR}


def code_of(reason):
    """pdf_fetch 的 reason → 状态码。认不出的算网络类（可重试）。"""
    return _REASON_CODE.get(reason or '', NETWORK_ERROR)


def resolve_id(doi, zotero_index=None):
    """DOI → 这篇在本平台的 id。实现在 `getpdf.resolve_id`（证据库 → Zotero → 按 DOI 生成）。"""
    from tools import getpdf
    return getpdf.resolve_id(doi, zotero_index)


def tier_of(pid, si=False):
    """这篇正文 / SI 现在到哪一档：structured / text / none（看盘，不看记忆）。"""
    d = paths.si_parsed_dir(pid) if si else paths.parsed_dir(pid)
    return pdf_parse.tier(d)


def _parse_text(pid, pdf_path):
    """快速文本层：PyMuPDF 本地几秒 → `parsed/full.md`（tier=text）。返回 (成功, 说明)。"""
    run = jobs.start(pid, 'parse_text', producer='fulltext')
    try:
        pdf_parse.parse_pdf_text(pdf_path, paths.parsed_dir(pid, create=True))
    except Exception as e:
        jobs.fail(run, str(e)[:200])
        return False, str(e)[:160]
    jobs.finish(run)
    return os.path.exists(paths.fulltext(pid)), ''


def _parse(pid, pdf_path):
    """PDF → `parsed/full.md`（MineRU，structured）。记时、记账。返回 (成功, 秒, 说明)。"""
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


def _parse_si_structured(pid, src):
    """SI 原件 → `si_parsed/full.md`（pdf 走 MineRU，docx 直读）。返回 (成功, 说明)。"""
    run = jobs.start(pid, 'parse_si', producer='fulltext')
    try:
        pdf_parse.parse_document(src, paths.si_parsed_dir(pid, create=True), reuse=True)
    except Exception as e:
        jobs.fail(run, str(e)[:200])
        return False, str(e)[:80]
    jobs.finish(run)
    ok = tier_of(pid, si=True) == pdf_parse.TIER_STRUCTURED
    return ok, '' if ok else '没产出 full.md'


class Upgrader:
    """后台把快速层升级成 MineRU 那一档：**一条线程、串行**，不挡下一篇的下载。

    2026-10-02 的教训：MineRU 一篇 pending 了半小时，整个取全文队列跟着停，PDF 在盘上却 0 字可读。
    现在拿到 PDF 先出快速层（几秒），MineRU 排在这里慢慢等；成功覆盖 full.md，失败快速层照旧可用。
    """

    def __init__(self):
        import queue
        self.q = queue.Queue()
        self.state = {}                      # (pid, 'main'|'si') → 'queued' / 'structured' / 'failed:…'
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def add(self, pid, which, src):
        if (pid, which) in self.state:
            return
        self.state[(pid, which)] = 'queued'
        self.q.put((pid, which, src))

    def _run(self):
        while True:
            item = self.q.get()
            if item is None:
                return
            pid, which, src = item
            try:
                if which == 'main':
                    ok, _s, why = _parse(pid, src)
                else:
                    ok, why = _parse_si_structured(pid, src)
                self.state[(pid, which)] = 'structured' if ok else 'failed:' + (why or '')[:120]
            except Exception as e:           # 线程里炸了也只影响这一篇的升级
                self.state[(pid, which)] = 'failed:%s' % str(e)[:120]

    def join(self):
        self.q.put(None)
        self._t.join()


def one(doi, zotero_index=None, allow_fetch=True, use_zotero=True, upgrader=None):
    """一篇 → dict(doi, id, ok, code, retryable, stage, tier, route, source, secs, chars, why, si)。**不抛异常**。

    `allow_fetch=False` 时只走前三层（不向出版商发任何请求）——
    「先看看手上有没有」这种问法不该触发一次真实下载。
    `upgrader`（`Upgrader`）给了：PDF 先出快速文本层就返回，MineRU 交给它在后台做；
    没给：快速层之后当场等 MineRU（命令行单篇、老调用方）。
    """
    t0 = time.time()
    doi = (doi or '').strip()
    if not pdf_fetch.is_doi(doi):
        return _fail_early(doi, '不像一个 DOI（应形如 10.1016/j.cej.2025.164092）')
    try:
        pid, in_zotero = resolve_id(doi, zotero_index)
    except paths.BadKeyError as e:
        return _fail_early(doi, str(e))
    route = {'r': ''}

    def done(ok, source, why='', code=None, stage='download'):
        chars = 0
        if ok:
            try:
                chars = os.path.getsize(paths.fulltext(pid))
            except OSError:
                chars = 0
        code = code or (OK if ok else NETWORK_ERROR)
        return {'doi': doi, 'id': pid, 'ok': ok, 'code': code, 'retryable': code in RETRYABLE,
                'stage': stage, 'tier': tier_of(pid), 'route': route['r'] or source,
                'source': source, 'secs': round(time.time() - t0, 1), 'chars': chars,
                'in_zotero': in_zotero, 'why': why,
                'si': _si_state(pid, allow_fetch, upgrader) if ok else ''}

    # ── 1. 缓存 ────────────────────────────────────────────────────
    if os.path.exists(paths.fulltext(pid)):
        # 正文早就有、SI 还缺（上次没取成）：趁这次有人要这篇，去补 SI。
        # 出版商确认过没挂的（si_status=none）不再去敲（2026-09-30：Angew 一篇正文在、SI 一直缺）
        from shared.kernel import catalog
        if allow_fetch and catalog.si_status(pid) == catalog.SI_UNKNOWN:
            try:
                _land(doi, allow_fetch, zotero_index, use_zotero)
            except Exception as e:
                log.warn('%s 补 SI 时出错（正文不受影响）：%s', doi, str(e)[:120])
        # 只有快速层的：趁这次有人要，把 MineRU 那一档补上（后台，不挡）
        if (upgrader and allow_fetch and tier_of(pid) == pdf_parse.TIER_TEXT
                and os.path.exists(paths.local_pdf(pid))):
            upgrader.add(pid, 'main', paths.local_pdf(pid))
        return done(True, SRC_CACHE)

    # ── 2～4. 落成本地正本（本地 → Zotero 复制 → 真去取）───────────
    had_local = os.path.exists(paths.local_pdf(pid))
    run = None if had_local else jobs.start(pid, 'fetch', producer='fulltext')
    try:
        landed = _land(doi, allow_fetch, zotero_index, use_zotero)
    except Exception as e:                    # 浏览器没开、网络断：这篇算失败，整批照跑
        if run:
            jobs.fail(run, str(e)[:200])
        return done(False, SRC_FETCH if allow_fetch else '', '取的时候出错：%s' % str(e)[:160],
                    code=NETWORK_ERROR)
    if not landed['ok']:
        if run:
            jobs.fail(run, landed.get('note') or 'no_pdf')
        code = code_of(landed.get('reason')) if allow_fetch else NOT_FETCHED
        return done(False, SRC_FETCH if allow_fetch else '', landed.get('note') or '没取到', code=code)
    if run:
        jobs.finish(run)
    source = {'local': SRC_LOCAL, 'zotero': SRC_ZOTERO, 'fetch': SRC_FETCH}.get(
        landed.get('source'), SRC_LOCAL)
    if source == SRC_FETCH:
        route['r'] = 'oa' if landed.get('reason') == 'oa' else 'browser_pdf'

    # ── 解析：先快速层（几秒），MineRU 后台补 ─────────────────────
    ok_text, why_text = _parse_text(pid, landed['pdf'])
    if not allow_fetch:
        # 只查不取：本地抽字几秒、不花钱，做；MineRU 要排队几分钟到半小时，不在「问一下」里等
        if ok_text:
            return done(True, source, stage='parse_text')
        return done(False, source, '手上有 PDF，快速文本层出不来（%s）；要 MineRU 就正常提交一次' % why_text,
                    code=PARSE_PENDING, stage='parse_text')
    if upgrader:
        upgrader.add(pid, 'main', landed['pdf'])
        if ok_text:
            return done(True, source, stage='parse_text')
        return done(False, source, '快速文本层出不来（%s），MineRU 在后台解析' % why_text,
                    code=PARSE_PENDING, stage='parse_structured')
    ok, _s, why = _parse(pid, landed['pdf'])
    if ok or ok_text:
        return done(True, source, '' if ok else 'MineRU 没成（%s），先用快速文本层' % why,
                    stage='parse_structured' if ok else 'parse_text')
    return done(False, source, why, code=PARSE_FAILED, stage='parse_structured')


def _fail_early(doi, why):
    return {'doi': doi, 'id': '', 'ok': False, 'code': NOT_FOUND, 'retryable': False,
            'stage': 'download', 'tier': pdf_parse.TIER_NONE, 'route': '', 'source': '',
            'secs': 0, 'chars': 0, 'why': why}


def _si_state(pid, allow_parse=True, upgrader=None):
    """这篇的 SI 到哪一步了；原件在、还没解析就**顺手解析**（2026-09-30）。

    → 'parsed' / 'pending'（后台 MineRU 在做）/ 'none'（没有 SI 原件）/ 'failed:<why>' / 'unparsed'（只查不取时不解析）。

    为什么在这里做：SI 解析原来只由落地流水线（host.ingest）做，而那条线 09-27 起随「后台自动建库」停了 ——
    Claude Science 取了两篇，si.pdf 都在盘上，却一篇都没解析，它看不到软件、力场、泛函这些只写在 SI 里的细节。
    2026-10-04 起同正文一样分两层：先快速层（pdf 本地抽字 / docx 直读），pdf 的 MineRU 交给 upgrader 后台做。
    """
    src = paths.find_local_si(pid)
    t = tier_of(pid, si=True)
    if t != pdf_parse.TIER_NONE:
        if t == pdf_parse.TIER_TEXT and upgrader and src and allow_parse:
            upgrader.add(pid, 'si', src)
        return 'parsed'
    if not src:
        return 'none'
    if not allow_parse:
        return 'unparsed'
    if not upgrader:
        ok, why = _parse_si_structured(pid, src)
        return 'parsed' if ok else 'failed:%s' % why
    try:
        pdf_parse.parse_document_text(src, paths.si_parsed_dir(pid, create=True))
    except Exception as e:
        log.info('%s 的 SI 快速层没出来（%s），等 MineRU', pid, str(e)[:80])
    t = tier_of(pid, si=True)
    if t != pdf_parse.TIER_STRUCTURED:        # 快速层出了或没出，pdf 都交给 MineRU 补
        upgrader.add(pid, 'si', src)
    return 'parsed' if t != pdf_parse.TIER_NONE else 'pending'


def _land(doi, allow_fetch, zotero_index, use_zotero=True):
    """真正去落地。**单独一个函数是为了能在测试里替换掉**（别真敲出版商）。"""
    from tools import getpdf
    return getpdf.land(doi, with_si=True, allow_fetch=allow_fetch,
                       zotero_index=zotero_index, use_zotero=use_zotero)


def publisher_of(doi):
    """DOI 前缀 = 出版商（10.1002 Wiley、10.1126 Science、10.1021 ACS…）：人机验证是按站点来的。"""
    return (doi or '').split('/', 1)[0].lower()


def many(dois, allow_fetch=True, gap=None, progress=None, limit=3, use_zotero=True, notify=None):
    """一批 DOI → 一批结果。**取是串行的，20 秒间隔不能省**。

    为什么默认只收 3 篇（`limit`）：出版商风控封的是**整个机构的 IP**，
    而模型不知道这个代价有多重。真要一整批，走 `getpdf_batch` 那条人点的路。

    `progress` 给一个文件路径就会边跑边写进度 —— 这是「发起 + 轮询」的那半。
    下载都跑完就标 `done`（新作业可以交了），MineRU 升级还在后台的标 `upgrading`。
    `use_zotero=False`：完全不碰 Zotero（不问它的 DOI 索引、不去它那找附件）—— Claude Science 那条路。
    `notify(标题, 正文)`：撞上人机验证时喊人（主力机桌面弹提醒）；每家出版商只喊一次。
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
    if use_zotero and not all(_cached(d) for d in dois):
        try:
            index = getpdf.doi_index()         # Zotero 里已有的先认出来，能省一次下载
        except Exception as e:
            log.warn('取 Zotero 的 DOI 索引失败（不影响，只是可能重下）：%s', str(e)[:120])

    res, t0 = {}, time.time()
    # 心跳：解析一篇大文献要好几分钟，期间原来进度一动不动 —— Claude Science 看着「用时卡在 34.8 秒」
    # 以为队列死了、停止轮询（2026-10-02）。现在每 HEARTBEAT_S 秒重写一次：正在处理哪篇、已经多久。
    now = {'doi': '', 'since': t0}
    stop = threading.Event()
    def _beat():
        while not stop.wait(HEARTBEAT_S):
            _write_progress(progress, dois, _ordered(dois, res), t0, done=False, current=now)
    threading.Thread(target=_beat, daemon=True).start()
    up = Upgrader() if allow_fetch else None
    try:
        _many_loop(dois, res, t0, now, index, allow_fetch, use_zotero, gap, progress, up, notify)
    finally:
        stop.set()
    out = _ordered(dois, res)
    if not up:
        _write_progress(progress, dois, out, t0, done=True)
        return out
    # 下载都完了：先标 done（新作业可以交了），MineRU 升级在这里等完，进程才退出
    _write_progress(progress, dois, out, t0, done=True, upgrading=bool(up.state))
    up.join()
    for i, r in enumerate(out):
        if not r.get('id'):
            continue
        if r.get('code') == PARSE_PENDING:
            if os.path.exists(paths.fulltext(r['id'])):          # 后台 MineRU 出来了
                out[i] = dict(r, ok=True, code=OK, retryable=False, why='',
                              chars=os.path.getsize(paths.fulltext(r['id'])))
            else:
                out[i] = dict(r, code=PARSE_FAILED, retryable=False,
                              why=up.state.get((r['id'], 'main'), '') or r.get('why', ''))
        out[i]['tier'] = tier_of(r['id'])
        if out[i].get('si') == 'pending':
            out[i]['si'] = 'parsed' if tier_of(r['id'], si=True) != pdf_parse.TIER_NONE else 'failed:MineRU 没成'
    # MineRU 等完时，进度文件可能已经是**下一个作业**的了（done 之后就允许交新的）—— 别盖掉人家的
    if _progress_owner(progress) == _job_id(t0):
        _write_progress(progress, dois, out, t0, done=True)
    return out


def _job_id(t0):
    return '%d-%d' % (os.getpid(), int(t0 * 1000))


def _progress_owner(path):
    import json
    try:
        return json.load(io.open(path, encoding='utf-8')).get('job', '')
    except (OSError, ValueError, TypeError):
        return ''


HEARTBEAT_S = 15
RETRY_COOLDOWN = 60        # 撞上人机验证的，整批跑完后歇多久再补试一次


def _ordered(dois, res):
    return [res[d] for d in dois if d in res]


def _deferred(doi, why):
    return {'doi': doi, 'id': '', 'ok': False, 'code': CAPTCHA_REQUIRED, 'retryable': True,
            'stage': 'download', 'tier': pdf_parse.TIER_NONE, 'route': '', 'source': '',
            'secs': 0, 'chars': 0, 'deferred': True, 'why': why}


def _many_loop(dois, res, t0, now, index, allow_fetch, use_zotero, gap, progress, up=None, notify=None):
    """串行跑一遍；**撞上人机验证的出版商，后面同家的先跳过，别家照跑**（2026-10-04 需求 P0-3）。

    原来撞上验证就整批等着补试，其它出版商的也跟着干等。现在：同一家的暂缓（不去敲 —— 验证是按站点的，
    再敲也是挡），别家的继续；跑完一轮歇 RETRY_COOLDOWN 秒，撞上的和暂缓的**每家先试一篇**，
    过了就接着跑这家剩下的，还挡着就整家标 CAPTCHA_REQUIRED（retryable），等人点完再交一次。
    """
    blocked_pub, warned = set(), set()
    last_fetch = {'t': 0.0}

    def _polite():
        # 只有**真去取了**才需要礼貌间隔；命中缓存/本地的不算敲出版商
        wait = gap - (time.time() - last_fetch['t'])
        if last_fetch['t'] and gap > 0 and wait > 0:
            time.sleep(wait)

    def _run(doi):
        now.update(doi=doi, since=time.time())
        r = one(doi, zotero_index=index, allow_fetch=allow_fetch, use_zotero=use_zotero, upgrader=up)
        if r.get('source') == SRC_FETCH:
            last_fetch['t'] = time.time()
        res[doi] = r
        _write_progress(progress, dois, _ordered(dois, res), t0, done=False)
        if allow_fetch and blocked(r):
            pub = publisher_of(doi)
            blocked_pub.add(pub)
            if notify and pub not in warned:
                warned.add(pub)
                try:
                    notify('取全文撞上人机验证',
                           '%s 被挡住了。「取全文用的浏览器」里停在验证页的那个标签已经切到最前面，点一下通过，再让 Claude 续跑。' % doi)
                except Exception as e:
                    log.info('桌面提醒没发出去：%s', str(e)[:80])
        return r

    held = []
    for doi in dois:
        if allow_fetch and publisher_of(doi) in blocked_pub:
            held.append(doi)
            res[doi] = _deferred(doi, '同一家出版商前一篇撞上人机验证，这篇先没去敲（暂缓）')
            _write_progress(progress, dois, _ordered(dois, res), t0, done=False)
            continue
        if allow_fetch:
            _polite()
        _run(doi)

    # 补试：撞上的 + 暂缓的。歇一会儿再来（2026-09-30：RSC 的 Cloudflare 时有时无，隔几分钟就过了）
    again = [d for d in dois if allow_fetch and (d in held or blocked(res[d]))]
    if not again:
        return
    log.info(f'{len(again)} 篇撞上人机验证或被暂缓，歇 {RETRY_COOLDOWN} 秒后每家先试一篇')
    now.update(doi='（等人机验证放行，%d 秒后补试）' % RETRY_COOLDOWN, since=time.time())
    time.sleep(RETRY_COOLDOWN)
    still = set()
    for doi in again:
        if publisher_of(doi) in still:
            res[doi] = _deferred(doi, '这家出版商还在人机验证，没去敲；人点完后再交一次（fulltext_retry）')
            continue
        _polite()
        if blocked(_run(doi)):
            still.add(publisher_of(doi))


def blocked(r):
    """这篇是不是被人机验证 / 验证页挡住的（值得过一会儿再试，而不是没权限、没链接）。"""
    if r.get('ok'):
        return False
    if r.get('code'):
        return r['code'] == CAPTCHA_REQUIRED
    why = r.get('why') or ''
    return any(pdf_fetch.REASONS[k] in why for k in ('captcha', 'not_pdf'))


_PROGRESS_LOCK = threading.Lock()     # 心跳线程和主流程都会写进度文件，别同时写


def _write_progress(path, dois, results, t0, done, current=None, upgrading=False):
    if not path:
        return
    with _PROGRESS_LOCK:
        _write_progress_locked(path, dois, results, t0, done, current, upgrading)


def _write_progress_locked(path, dois, results, t0, done, current=None, upgrading=False):
    import json
    finished = len(results) if done else sum(1 for r in results if not r.get('deferred'))
    payload = {'total': len(dois), 'finished': finished, 'done': done,
               'elapsed': round(time.time() - t0, 1), 'results': results, 'job': _job_id(t0)}
    if upgrading:
        payload['upgrading'] = True          # 下载完了，MineRU 还在后台补表格（不挡新作业）
    if current and current.get('doi') and not done:
        payload['current'] = {'doi': current['doi'], 'for_s': round(time.time() - current['since'])}
    try:
        tmp = path + '.tmp'
        io.open(tmp, 'w', encoding='utf-8').write(json.dumps(payload, ensure_ascii=False, indent=1))
        os.replace(tmp, path)                 # 原子替换：读的那边不会读到半截
    except OSError:
        pass                                   # 写不下进度不该让作业本身失败


def summarize(results):
    """一批结果 → 给模型看的文本。**每篇都说清楚是怎么来的、花了多久**。"""
    if not results:
        return '没有可处理的 DOI。'
    lines = []
    for r in results:
        if r['ok']:
            lines.append('✓ %s → %s（%s，%.0fs，%d 字符%s）'
                         % (r['doi'], r['id'], _cn(r['source']), r['secs'], r['chars'],
                            '，快速文本层' if r.get('tier') == pdf_parse.TIER_TEXT else ''))
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
