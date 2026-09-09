# -*- coding: utf-8 -*-
"""fulltext · 一个 DOI → **LLM 读得懂的全文**。四层回退，全程计时。

## 这是整条路上缺的那一环

通用 LLM 拿不到付费墙后面的东西 —— 它能搜到的只有摘要和开放获取。
而这台机器有三样它没有的：机构订阅权限（靠出口 IP）、一个过过人机验证的
真实浏览器、MineRU 解析额度。**把这三样接到模型手上，付费墙就跨过去了。**

## 四层回退（越靠前越快越省）

    1. 缓存      `raw/<id>/parsed/full.md` 已经在      → 秒回，零成本
    2. 本地正本  `raw/<id>/main.pdf` 已经在            → 只解析
    3. Zotero    库里这篇有 PDF 附件                    → 只解析，不下载
    4. 取        借浏览器向出版商要                      → 20 秒间隔，慢是故意的

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
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters import pdf_fetch, pdf_parse, zotero_client as zc
from shared.kernel import jobs, paths
from shared.kernel.log import get_logger

log = get_logger('getpdf')

# 来源标签：给模型看的「这篇是怎么来的」，也用来解释为什么快/慢
SRC_CACHE = 'cache'        # 解析过了，秒回
SRC_LOCAL = 'local'        # 本地有 PDF，只花解析
SRC_ZOTERO = 'zotero'      # Zotero 库里有附件，只花解析
SRC_FETCH = 'fetch'        # 真去出版商取了


def resolve_id(doi, zotero_index=None):
    """DOI → 这篇在本平台的 id。

    **优先用 Zotero 编号**：这篇要是已经在他自己库里，就该跟已有的精读、
    抽取结果落在同一个目录下，而不是另起一份。库里没有的才按 DOI 生成 id
    （2026-09-07 放宽身份证之后才可能，见 `paths.paper_id_from_doi`）。
    """
    doi = (doi or '').strip().lower()
    if zotero_index:
        k = zotero_index.get(doi)
        if k:
            return k, True
    return paths.paper_id_from_doi(doi), False


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
                'in_zotero': in_zotero, 'why': why}

    # ── 1. 缓存 ────────────────────────────────────────────────────
    if os.path.exists(paths.fulltext(pid)):
        return done(True, SRC_CACHE)

    # ── 2. 本地正本 ────────────────────────────────────────────────
    local = paths.local_pdf(pid)
    if os.path.exists(local):
        ok, _s, why = _parse(pid, local)
        return done(ok, SRC_LOCAL, why)

    # ── 3. Zotero 库里已有附件（不下载，直接解析）──────────────────
    if in_zotero:
        try:
            att = zc.find_pdf(pid)
        except Exception as e:
            att = None
            log.warn('%s 找 Zotero 附件失败：%s', pid, str(e)[:120])
        if att and os.path.exists(att):
            ok, _s, why = _parse(pid, att)
            return done(ok, SRC_ZOTERO, why)

    # ── 4. 真去取（这一层才有出版商风控的代价）─────────────────────
    if not allow_fetch:
        return done(False, '', '手上没有，而且这次不允许去取（allow_fetch=False）')
    run = jobs.start(pid, 'fetch', producer='fulltext')
    r = _fetch_one(doi)
    if not r['ok']:
        jobs.fail(run, r['reason'])
        return done(False, SRC_FETCH,
                    '没取到 —— %s' % pdf_fetch.REASONS.get(r['reason'], r['reason']))
    jobs.finish(run)
    # 取到的 PDF 收成这篇的本地正本，下次就走第 2 层
    try:
        os.makedirs(os.path.dirname(local), exist_ok=True)
        with io.open(r['path'], 'rb') as src, io.open(local, 'wb') as dst:
            dst.write(src.read())
    except OSError as e:
        log.warn('%s 收正本失败（不影响本次解析）：%s', pid, str(e)[:120])
        local = r['path']
    ok, _s, why = _parse(pid, local)
    return done(ok, SRC_FETCH, why)


def _fetch_one(doi):
    """真正去取。**单独一个函数是为了能在测试里替换掉**（别真敲出版商）。"""
    from tools import getpdf                  # 同一个工具包内，不违反工具隔离
    return getpdf.fetch_one(doi)


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
    if allow_fetch or True:
        try:
            index = getpdf.doi_index()         # 库里已有的先认出来，能省一次下载
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
    _write_progress(progress, dois, out, t0, done=True)
    return out


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
        tail = ('\n\n下一步：用 library_outline 看菜单（几百 token），'
                '再用 library_section 只取要看的那几节 —— 别一口气读全文。\n'
                'id：' + '、'.join(r['id'] for r in ok))
    return '\n'.join(lines) + tail


def _cn(source):
    return {SRC_CACHE: '早就解析过', SRC_LOCAL: '本地有 PDF',
            SRC_ZOTERO: 'Zotero 库里有', SRC_FETCH: '刚去取的'}.get(source, source)
