# -*- coding: utf-8 -*-
"""chemdb · 化学数据库（SciFinder / Reaxys）检索 —— 借人已经登录好的浏览器读结果页

**为什么有这块（2026-10-08 用户定）**：SciFinder、Reaxys 一搜就是几十上百条文献和专利，
人一条条点开筛很费时间；Claude Science 读得快，但它进不去（要学校订阅 + 个人登录）。

查证过的现实（2026-10-08，见 docs/reference）：
  - SciFinder 的官方接口只给合作软件（电子实验记录本），搜索只回一个「去网页看」的链接，
    登录必须人在浏览器前 —— 不是给程序取数据用的。
  - Reaxys 有真数据接口，但要单位另外订接口，网页订阅不含。
所以这块的形状和 pdf_fetch 一样：**不自己发请求，接管主力机上那个「取全文用的浏览器」**，
人在里面登录一次（SciFinder 个人账号、Reaxys 机构登录），之后按人的频率搜、读结果页文字。

⚠ 只读：搜索、翻页、读文字。**不导出、不点详情批量下载、不登录**（登录永远是人做）。
⚠ 频率（每次间隔、每天上限）由调用方管（host/mcp/science.py），这块只管「怎么在页面上搜」。
⚠ 结果页是前端渲染的：等到结果数出现、文字不再变长才读。

对外接口：
  | 函数 | 说明 |
  |---|---|
  | `search(db, query, kind='references', max_chars=30000)` | 搜一次 → dict（见下） |
  | `page(db, n, max_chars=30000)` | 上一次搜索结果的第 n 页 → dict |
  | `page_url(db, url, n)` | 结果页网址换页码（纯函数，自测用） |
  | `clean_text(text)` / `count_of(db, title, text)` | 页面文字去样板 / 读结果数（纯函数） |

返回 dict：ok, code, db, kind, query, page, url, title, count, text, chars, truncated, why。
code：OK / LOGIN_REQUIRED（人去浏览器登录）/ NO_RESULTS / NO_SEARCH（翻页前没搜过）/
NAVIGATE_FAILED / TIMEOUT。只有「浏览器连不上 / 没装 playwright」才抛异常（沿用 pdf_fetch 的两个异常）。
"""
import contextlib
import re
import time

from shared.adapters import pdf_fetch
from shared.kernel.log import get_logger

log = get_logger('chemdb')

DBS = ('scifinder', 'reaxys')
KINDS = ('references', 'substances', 'reactions')

# 页面在哪、长什么样 —— 网站改版只改这里
SITE = {
    'scifinder': {
        'host': 'scifinder-n.cas.org',
        'home': 'https://scifinder-n.cas.org/',
        'input': '#search-text-input',
        'submit': '#submit-search-button',
        # 总览页（/search/all/…）上各类各有一个「View All …」
        'view_all': {'references': 'View All References', 'substances': 'View All Substances',
                     'reactions': 'View All Reactions'},
        # 结果页网址：/search/<reference|substance|reaction>/<id>/<页码>
        'page_re': r'(/search/(?:reference|substance|reaction)/[^/?#]+/)(\d+)',
        'login_re': r'sso\.cas\.org|/login',
    },
    'reaxys': {
        'host': 'reaxys.com',
        'home': 'https://www.reaxys.com/#/search/quick/query',
        'input': '#id-quick-search-input',
        'view_results': '.e2e-view-results',
        'card_word': {'references': 'Documents', 'substances': 'Substances', 'reactions': 'Reactions'},
        # 结果页网址：…/list/<uuid>/<页码>/desc/…
        'page_re': r'(/list/[^/]+/)(\d+)(/)',
        'login_re': r'#/login|id\.elsevier\.com',
    },
}

# 每页都有、对判断没用的行
_BOILER = re.compile(
    r'^(Skip to .*|Copyright ©.*|All content on this site:.*|We use cookies.*|Cookie Settings|'
    r'Help Contact Us Legal|Elsevier|RELX™|Feedback|Remote access|Terms and Conditions|Privacy policy|'
    r'\(opens in a new window\)|About content|Accessibility|Contact support|History|Alerts|'
    r'Resource Center|Draw|Return to Home|Zoom structures|Zoom out|Zoom in|Sort descending|Sort ascending)$')


# ══════════════════════════════════════════════════════════════════════
# 纯函数（自测覆盖）
# ══════════════════════════════════════════════════════════════════════

def check_db(db):
    db = (db or '').strip().lower()
    if db not in DBS:
        raise ValueError(f'db 只能是 {" / ".join(DBS)}（给了「{db}」）')
    return db


def check_kind(kind):
    kind = (kind or 'references').strip().lower()
    if kind not in KINDS:
        raise ValueError(f'kind 只能是 {" / ".join(KINDS)}（给了「{kind}」）')
    return kind


def page_url(db, url, n):
    """结果页网址换成第 n 页；不是结果页返回 ''。"""
    m = re.search(SITE[db]['page_re'], url or '')
    if not m:
        return ''
    return url[:m.start(2)] + str(int(n)) + url[m.end(2):]


def page_no(db, url):
    m = re.search(SITE[db]['page_re'], url or '')
    return int(m.group(2)) if m else 0


def is_login(db, url):
    return bool(re.search(SITE[db]['login_re'], url or ''))


def clean_text(text):
    """去掉每页都有的样板行和空行，连续重复行只留一行。"""
    out, last = [], None
    for ln in (text or '').splitlines():
        s = ln.strip()
        if not s or _BOILER.match(s) or s == last:
            continue
        out.append(s)
        last = s
    return '\n'.join(out)


def count_of(db, title, text):
    """结果数（读不出来返回 None）。SciFinder 在正文「26 Results」；Reaxys 在标题「134 Documents for …」。"""
    if db == 'reaxys':
        m = re.search(r'([\d,]+)\s+(?:Documents|Substances|Reactions)\b', title or '') \
            or re.search(r'([\d,]+)\s+(?:Documents|Substances|Reactions)\b', text or '')
    else:
        m = re.search(r'(?m)^([\d,]+)\s+Results?$', text or '') or re.search(r'of\s+([\d,]+)\s+Results?', text or '')
    return int(m.group(1).replace(',', '')) if m else None


def _result(db, **kw):
    r = {'ok': False, 'code': 'OK', 'db': db, 'kind': None, 'query': None, 'page': 0, 'url': '',
         'title': '', 'count': None, 'text': '', 'chars': 0, 'truncated': False, 'why': ''}
    r.update(kw)
    return r


# ══════════════════════════════════════════════════════════════════════
# 浏览器
# ══════════════════════════════════════════════════════════════════════
# 自己连，不用 pdf_fetch._connect：那个连上时会清扫多余的出版商标签，可能关掉取全文作业正开着的那页。
# 每次调用连上、用完就断：MCP 的 HTTP 服务一个请求一个线程，按线程缓存连接会把驱动进程漏在后台。
@contextlib.contextmanager
def _session():
    target = pdf_fetch.cdp_url()
    sync_playwright = pdf_fetch._sync_api()
    pw = sync_playwright().start()
    try:
        try:
            browser = pw.chromium.connect_over_cdp(target)
        except Exception as e:
            raise pdf_fetch.BrowserUnavailable(
                f'连不上主力机的「取全文用的浏览器」（{target}）：{e}。它要开着，SciFinder / Reaxys 要在里面登录过。')
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        yield browser, ctx
    finally:
        try:
            pw.stop()                     # 只断开连接，不关浏览器、不关标签（登录和结果都留在上面）
        except Exception:
            pass


def _tab(browser, ctx, db):
    """这个库专用的标签：已有就复用（登录状态、上次的结果都在上面），没有就后台开一个。"""
    host = SITE[db]['host']
    mine = [p for p in ctx.pages if host in (p.url or '')]
    if mine:
        return mine[-1]
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
    except Exception as e:
        log.warn(f'后台开标签失败（{str(e)[:80]}），退回前台开法')
        return ctx.new_page()


def _body(pg):
    try:
        return pg.evaluate('document.body ? document.body.innerText : ""') or ''
    except Exception:
        return ''


def _settle(pg, ready, timeout=45):
    """等到 ready(text) 为真、且正文两次读数长度不变（前端还在往里填就再等）。→ 是否等到。"""
    end, prev = time.time() + timeout, -1
    while time.time() < end:
        t = _body(pg)
        if ready(t) and len(t) == prev:
            return True
        prev = len(t)
        pg.wait_for_timeout(1500)
    return False


def _read(pg, db, max_chars, **kw):
    text = clean_text(_body(pg))
    title = ''
    try:
        title = pg.title()
    except Exception:
        pass
    full = len(text)
    return _result(db, ok=True, url=pg.url, title=title, count=count_of(db, title, text),
                   page=page_no(db, pg.url) or 1, text=text[:max_chars], chars=full,
                   truncated=full > max_chars, **kw)


def _goto(pg, url):
    try:
        pg.goto(url, wait_until='domcontentloaded', timeout=60000)
        return True
    except Exception as e:
        log.warn(f'打不开 {url}：{str(e)[:120]}')
        return False


_HAS_RESULTS = re.compile(r'\b\d[\d,]*\s+(Results?|Documents|Substances|Reactions)\b')


def _search_scifinder(pg, query, kind, max_chars):
    s = SITE['scifinder']
    if not _goto(pg, s['home']):
        return _result('scifinder', code='NAVIGATE_FAILED', why='SciFinder 首页打不开')
    try:
        pg.wait_for_selector(s['input'], timeout=30000)
    except Exception:
        if is_login('scifinder', pg.url):
            return _result('scifinder', code='LOGIN_REQUIRED', url=pg.url,
                           why='SciFinder 要登录：请人在主力机「取全文用的浏览器」里登录（勾 Stay signed in）')
        return _result('scifinder', code='TIMEOUT', url=pg.url, why='等不到搜索框')
    pg.fill(s['input'], query)
    pg.click(s['submit'])
    try:
        pg.wait_for_url(re.compile(r'/search/'), timeout=45000)
    except Exception:
        return _result('scifinder', code='TIMEOUT', url=pg.url, why='提交后没跳到结果页')
    # 总览页是分块加载的（2026-10-08 实测：物质、反应先到，文献那块晚好几秒）——
    # 专门等要的那个「View All …」；等满了还没有才算这一类没结果
    want = s['view_all'][kind]
    _settle(pg, lambda t: want in t or 'No results' in t, timeout=45)
    link = pg.locator(f'text={want}')
    if link.count() == 0:
        r = _read(pg, 'scifinder', max_chars)
        r.update(ok=True, code='NO_RESULTS', count=0, why=f'这次搜索没有 {kind} 结果（总览页附在 text 里）')
        return r
    link.first.click()
    try:
        pg.wait_for_url(re.compile(SITE['scifinder']['page_re']), timeout=45000)
    except Exception:
        return _result('scifinder', code='TIMEOUT', url=pg.url, why=f'点了 {want} 没跳到列表页')
    ok = _settle(pg, lambda t: bool(_HAS_RESULTS.search(t)), timeout=45)
    r = _read(pg, 'scifinder', max_chars)
    if not ok:
        r.update(code='TIMEOUT', why='列表页还在加载，读到的可能不全')
    return r


def _search_reaxys(pg, query, kind, max_chars):
    s = SITE['reaxys']
    if not _goto(pg, s['home']):
        return _result('reaxys', code='NAVIGATE_FAILED', why='Reaxys 打不开')
    try:
        pg.wait_for_selector(s['input'], timeout=30000)
    except Exception:
        if is_login('reaxys', pg.url):
            return _result('reaxys', code='LOGIN_REQUIRED', url=pg.url,
                           why='Reaxys 要登录：请人在主力机「取全文用的浏览器」里登录（机构登录或 Elsevier 账号）')
        return _result('reaxys', code='TIMEOUT', url=pg.url, why='等不到搜索框')
    pg.fill(s['input'], query)
    pg.keyboard.press('Enter')
    # 预览页：Reaxys 把一句话拆成几组子查询，各给一个数和一个 View Results
    if not _settle(pg, lambda t: 'View Results' in t or 'No results' in t, timeout=60):
        return _result('reaxys', code='TIMEOUT', url=pg.url, why='等不到结果预览')
    preview = clean_text(_body(pg))
    word = s['card_word'][kind]
    # 第一张「<数> <类>」的卡片 = 最贴近整句话的那组（Reaxys 按从严到宽排）
    idx = pg.evaluate("""([sel, word]) => {
        const bs = [...document.querySelectorAll(sel)];
        for (let i = 0; i < bs.length; i++) {
            let e = bs[i];
            for (let up = 0; up < 8 && e; up++, e = e.parentElement) {
                const t = e.innerText || '';
                const m = t.match(/(\\d[\\d,]*)\\s*\\n?\\s*(Documents|Substances|Reactions)/);
                if (m) { if (m[2] === word) return i; break; }
            }
        }
        return -1; }""", [s['view_results'], word])
    if idx < 0:
        r = _result('reaxys', ok=True, code='NO_RESULTS', count=0, url=pg.url, text=preview[:max_chars],
                    chars=len(preview), why=f'预览里没有 {word} 这一组（预览附在 text 里）')
        return r
    pg.locator(s['view_results']).nth(idx).click()
    try:
        pg.wait_for_url(re.compile(SITE['reaxys']['page_re']), timeout=60000)
    except Exception:
        return _result('reaxys', code='TIMEOUT', url=pg.url, why='点了 View Results 没跳到列表页')
    ok = _settle(pg, lambda t: bool(_HAS_RESULTS.search(t)) and ('Cited' in t or 'Abstract' in t), timeout=60)
    r = _read(pg, 'reaxys', max_chars, preview=preview[:4000])
    if not ok:
        r.update(code='TIMEOUT', why='列表页还在加载，读到的可能不全')
    return r


# ══════════════════════════════════════════════════════════════════════
# 对外
# ══════════════════════════════════════════════════════════════════════

def search(db, query, kind='references', max_chars=30000):
    """在 SciFinder / Reaxys 里搜一次，读结果列表第 1 页的文字。"""
    db, kind = check_db(db), check_kind(kind)
    query = (query or '').strip()
    if not query:
        raise ValueError('query 不能是空的')
    log.info(f'{db} 搜索（{kind}）：{query}')
    fn = _search_scifinder if db == 'scifinder' else _search_reaxys
    with _session() as (browser, ctx):
        pg = _tab(browser, ctx, db)
        try:
            r = fn(pg, query, kind, max_chars)
        except Exception as e:
            log.warn(f'{db} 搜索出错：{type(e).__name__}: {str(e)[:200]}')
            r = _result(db, code='TIMEOUT', url=getattr(pg, 'url', ''), why=f'{type(e).__name__}: {str(e)[:200]}')
    r.update(kind=kind, query=query)
    return r


def page(db, n, max_chars=30000):
    """上一次搜索（这个库的标签上停着的那个结果列表）的第 n 页。"""
    db = check_db(db)
    n = int(n)
    if n < 1:
        raise ValueError('页码从 1 开始')
    with _session() as (browser, ctx):
        return _page_on(_tab(browser, ctx, db), db, n, max_chars)


def _page_on(pg, db, n, max_chars):
    url = page_url(db, pg.url, n)
    if not url:
        if is_login(db, pg.url):
            return _result(db, code='LOGIN_REQUIRED', url=pg.url, why='要登录：请人在主力机浏览器里登录')
        return _result(db, code='NO_SEARCH', url=pg.url, why='这个库的标签上没有结果列表，先 search')
    if not _goto(pg, url):
        return _result(db, code='NAVIGATE_FAILED', url=url, why='翻页打不开')
    if db == 'reaxys':
        # Reaxys 是 # 路由，goto 同一文档只换 hash 时不一定重画，补一次刷新
        pg.reload(wait_until='domcontentloaded')
    ok = _settle(pg, lambda t: bool(_HAS_RESULTS.search(t)), timeout=45)
    r = _read(pg, db, max_chars)
    if not ok:
        r.update(code='TIMEOUT', why='列表页还在加载，读到的可能不全')
    return r
