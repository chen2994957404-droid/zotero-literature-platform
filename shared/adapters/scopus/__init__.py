# -*- coding: utf-8 -*-
"""scopus · Scopus 文献检索与「谁引用了它」—— 借人登录好的浏览器，按人的节奏查、读结果页

**为什么有这块（2026-10-09 用户定）**：Scopus 的被引数与「被引文献」列表是判断一篇文献分量、顺引用往后追的常用入口；
人查完截图给 Claude Science 太费事。用户原话：「跟 SciFinder 一样省去截图给 Claude Science 的过程，
遇到人机验证我都会来点，也只做少量需要的检索」。

⚠ 条款（Elsevier 网站条款，2026-10-09 读原文）：禁把内容与 AI 工具结合；禁自动程序持续检索抓取。用户知情后决定
按人的频率少量用。所以这块：**一次只读一页结果列表**，不导出、不批量翻页、不点进摘要页；遇到人机验证回
CAPTCHA_REQUIRED，人点。频率由调用方管。

页面（2026-10-09 实测）：
  - 结果页网址可以直接拼：/results/results.uri?src=s&sot=b&sdt=b&sort=<cp-f|plf-f|r-f>&s=<检索式>
  - 每条一行 `tr`，里面 `label[for="document-2-s2.0-<id>"]`（EID）、`h3 a`（标题）、`[data-testid=author-list] button`（作者）、
    `[data-component=document-source]`（刊名 + 卷期页）、`[data-testid=document-publication-year]`、
    被引数是一个指向「引用它的文献」检索的链接；上一行 `tr` 是文献类型（Article / Review …）与开放获取标记
  - 总数在正文：「183 篇文献」（中文界面）/「183 documents found」

对外接口：
  | 函数 | 说明 |
  |---|---|
  | `search(query, sort='relevance')` | 检索 → 第 1 页（query 不带字段代码时按 TITLE-ABS-KEY）|
  | `citing(n)` | 当前结果页第 n 条「谁引用了它」→ 那张列表的第 1 页 |
  | `page(n)` | 当前列表的第 n 页 |
  | `status()` | 标签在不在、是不是登录页 / 验证页 |
  | `build_query` / `results_url` / `parse_rows` / `parse_count` / `is_login` / `is_captcha` | 纯函数（自测覆盖） |
"""
import contextlib
import re
import time
import urllib.parse

from shared.adapters import pdf_fetch
from shared.kernel.log import get_logger

log = get_logger('scopus')

RESULTS = 'https://www.scopus.com/results/results.uri?src=s&sot=b&sdt=b&sort={sort}&s={q}'
SORTS = {'relevance': 'r-f', 'cited': 'cp-f', 'date': 'plf-f'}
_FIELD = re.compile(r'\b[A-Z][A-Z\-]{2,}\(')          # TITLE-ABS-KEY( / AUTH( / DOI( / REF( …
_COUNT = re.compile(r'([\d,]+)\s*(?:篇文献|documents? found|document results)')


# ══════════════════════════════════════════════════════════════════════
# 纯函数（自测覆盖）
# ══════════════════════════════════════════════════════════════════════

def build_query(query):
    """不带字段代码的词 → TITLE-ABS-KEY(词)；已经是 Scopus 检索式（含 TITLE-ABS-KEY( / AUTH( / DOI( …）就原样。"""
    q = (query or '').strip()
    if not q:
        raise ValueError('query 不能空')
    return q if _FIELD.search(q) else f'TITLE-ABS-KEY({q})'


def results_url(query, sort='relevance'):
    sort = (sort or 'relevance').strip().lower()
    if sort not in SORTS:
        raise ValueError(f'sort 只能是 {" / ".join(SORTS)}（给了「{sort}」）')
    return RESULTS.format(sort=SORTS[sort], q=urllib.parse.quote(build_query(query)))


def parse_count(text):
    m = _COUNT.search(text or '')
    return int(m.group(1).replace(',', '')) if m else None


def is_login(url):
    return 'id.elsevier.com' in (url or '') or '/signin' in (url or '').lower()


def is_captcha(text):
    t = (text or '').lower()
    return 'verify you are human' in t or 'unusual traffic' in t or '请验证您是真人' in t


def parse_rows(rows):
    """页面里抽出来的行 → [{rank, eid, title, authors, source, citation, year, cited, type, open_access, url, cited_by_url}]。"""
    out = []
    for r in rows or []:
        src = (r.get('source') or '').strip()
        parts = src.split(',', 1)
        cited = re.sub(r'[^\d]', '', r.get('cited') or '')
        typ = (r.get('type') or '').replace('\xa0', ' ')
        out.append({'rank': int(r['rank']) if (r.get('rank') or '').strip().isdigit() else None,
                    'eid': r.get('eid') or None, 'title': (r.get('title') or '').strip() or None,
                    'authors': [a.strip() for a in (r.get('authors') or []) if a.strip()],
                    'source': parts[0].strip() or None, 'citation': parts[1].strip() if len(parts) > 1 else None,
                    'year': int(r['year']) if (r.get('year') or '').strip().isdigit() else None,
                    'cited': int(cited) if cited else 0,
                    'type': (typ.split('•')[0].strip() or None) if typ else None,
                    'open_access': ('开放获取' in typ or 'Open access' in typ) if typ else None,
                    'url': r.get('href') or None, 'cited_by_url': r.get('cited_href') or None})
    return out


def _result(**kw):
    r = {'ok': False, 'code': 'OK', 'url': '', 'why': '', 'warnings': [], 'items': []}
    r.update(kw)
    return r


# ══════════════════════════════════════════════════════════════════════
# 浏览器
# ══════════════════════════════════════════════════════════════════════

_ROWS_JS = """() => [...document.querySelectorAll('tr')].filter(tr => tr.querySelector('label[for^="document-2-s2.0-"]')).map(tr => {
  const lab = tr.querySelector('label[for^="document-2-s2.0-"]'), a = tr.querySelector('h3 a');
  const cit = [...tr.querySelectorAll('a')].find(x => /results\\.uri\\?s=ref/i.test(x.getAttribute('href') || ''));
  const prev = tr.previousElementSibling;
  return {rank: (lab.innerText || '').trim(), eid: lab.getAttribute('for').replace('document-', ''),
          title: a ? a.innerText : '', href: a ? a.href : '',
          authors: [...tr.querySelectorAll('[data-testid=author-list] button')].map(b => b.innerText),
          source: (tr.querySelector('[data-component=document-source]') || {}).innerText || '',
          year: (tr.querySelector('[data-testid=document-publication-year]') || {}).innerText || '',
          cited: cit ? cit.innerText : '', cited_href: cit ? cit.href : '',
          type: prev && !prev.querySelector('label') ? prev.innerText : ''};
})"""


@contextlib.contextmanager
def _session():
    target = pdf_fetch.cdp_url()
    sync_playwright = pdf_fetch._sync_api()
    pw = sync_playwright().start()
    try:
        try:
            browser = pw.chromium.connect_over_cdp(target)
        except Exception as e:
            raise pdf_fetch.BrowserUnavailable(f'连不上主力机的「取全文用的浏览器」（{target}）：{e}。它要开着。')
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        yield browser, ctx
    finally:
        try:
            pw.stop()
        except Exception:
            pass


def _find_tab(ctx):
    mine = [p for p in ctx.pages if 'scopus.com' in (p.url or '')]
    return mine[-1] if mine else None


def _body(pg):
    try:
        return pg.evaluate('document.body ? document.body.innerText : ""') or ''
    except Exception:
        return ''


def _gate(pg, warnings):
    if is_login(pg.url):
        return _result(code='LOGIN_REQUIRED', url=pg.url, warnings=warnings,
                       why='Scopus 要重新登录：请人在主力机「取全文用的浏览器」里打开 scopus.com 登录')
    if is_captcha(_body(pg)):
        return _result(code='CAPTCHA_REQUIRED', url=pg.url, warnings=warnings,
                       why='Scopus 弹了人机验证：请人在主力机浏览器的 Scopus 标签里点完，再重交（同一检索当天有缓存）')
    return None


def _settle(pg, timeout=45):
    end, prev = time.time() + timeout, -1
    while time.time() < end:
        t = _body(pg)
        if is_captcha(t) or is_login(pg.url):
            return True
        n = len(pg.evaluate(_ROWS_JS) or [])
        if (n or '0 篇文献' in t or 'No documents' in t or '没有找到' in t) and len(t) == prev:
            return True
        prev = len(t)
        pg.wait_for_timeout(1500)
    return False


def _list(pg, warnings):
    t = _body(pg)
    items = parse_rows(pg.evaluate(_ROWS_JS))
    pages = pg.evaluate("""() => { const n = [...document.querySelectorAll('nav button, [class*=Pagination] button, [class*=pagination] button')]
        .map(b => parseInt((b.innerText || '').trim(), 10)).filter(x => !isNaN(x)); return n.length ? Math.max(...n) : null; }""")
    return _result(ok=True, code='OK' if items else 'NO_RESULTS', url=pg.url, warnings=warnings, items=items,
                   count=parse_count(t), pages=pages, page_size=len(items))


def _new_tab(browser, ctx):
    try:
        cdp = browser.new_browser_cdp_session()
        try:
            with ctx.expect_page(timeout=10000) as ev:
                cdp.send('Target.createTarget', {'url': 'about:blank', 'background': True})
            return ev.value
        finally:
            try:
                cdp.detach()
            except Exception:
                pass
    except Exception:
        return ctx.new_page()


def _go(url):
    warnings = []
    with _session() as (browser, ctx):
        # 标签没了（被关掉过）就自己开一个：登录状态存在浏览器里，不用重登；真掉了登录会落到登录页 → LOGIN_REQUIRED
        pg = _find_tab(ctx) or _new_tab(browser, ctx)
        bad = _gate(pg, warnings) if 'scopus.com' in (pg.url or '') else None
        if bad:
            return bad
        try:
            pg.goto(url, wait_until='load', timeout=60000)
        except Exception as e:
            return _result(code='NAVIGATE_FAILED', url=url, warnings=warnings, why=f'打不开 Scopus：{str(e)[:120]}')
        if not _settle(pg):
            return _gate(pg, warnings) or _result(code='TIMEOUT', url=pg.url, warnings=warnings, why='结果 45 秒没出来')
        return _gate(pg, warnings) or _list(pg, warnings)


def search(query, sort='relevance'):
    """检索一次 → 第 1 页。query：普通词（按题名 / 摘要 / 关键词）或 Scopus 检索式；sort：relevance / cited / date。"""
    r = _go(results_url(query, sort))
    r['query'] = build_query(query)
    r['sort'] = sort
    return r


def citing(n):
    """当前结果页第 n 条「谁引用了它」的列表（读那条被引数上的链接，再打开它）。"""
    n = int(n)
    with _session() as (browser, ctx):
        pg = _find_tab(ctx)
        hit = next((it for it in parse_rows(pg.evaluate(_ROWS_JS)) if it['rank'] == n), None) if pg else None
    if not hit:
        return _result(code='NOT_FOUND', why=f'当前 Scopus 结果页上没有第 {n} 条；先 search 或翻到那一页')
    if not hit.get('cited_by_url'):
        return _result(code='NO_RESULTS', why=f'第 {n} 条还没被引用过（cited=0）')
    r = _go(hit['cited_by_url'])
    r['citing_of'] = {k: hit.get(k) for k in ('eid', 'title', 'year', 'cited')}
    return r


def page(n):
    """当前列表的第 n 页（点分页条上的页码；只显示附近几页时远的点不到）。"""
    n = int(n)
    warnings = []
    with _session() as (browser, ctx):
        pg = _find_tab(ctx)
        if not pg:
            return _result(code='NOT_FOUND', why='浏览器里没有 Scopus 的标签')
        bad = _gate(pg, warnings)
        if bad:
            return bad
        first = (pg.evaluate(_ROWS_JS) or [{}])[0].get('eid')
        ok = pg.evaluate("""(n) => { const b = [...document.querySelectorAll('nav button, [class*=Pagination] button, [class*=pagination] button')]
            .find(x => (x.innerText || '').trim() === String(n)); if (!b) return false; b.click(); return true; }""", n)
        if not ok:
            return _result(code='NOT_FOUND', url=pg.url, why=f'分页条上没有第 {n} 页')
        end = time.time() + 40
        while time.time() < end:
            pg.wait_for_timeout(1500)
            rows = pg.evaluate(_ROWS_JS) or []
            if rows and rows[0].get('eid') != first:
                break
        return _gate(pg, warnings) or _list(pg, warnings)


def status():
    with _session() as (browser, ctx):
        pg = _find_tab(ctx)
        if not pg:
            return {'tab_open': False, 'url': '', 'login_page': False, 'captcha': False}
        return {'tab_open': True, 'url': pg.url, 'login_page': is_login(pg.url), 'captcha': is_captcha(_body(pg))}
