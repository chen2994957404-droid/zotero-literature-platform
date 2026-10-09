# -*- coding: utf-8 -*-
"""cnki · 中国知网（学位论文 / 期刊 / 会议 / 中国专利）—— 借人已经在用的浏览器，按人的节奏查、读页面

**为什么有这块（2026-10-09 用户定「需要的都可以用起来」）**：国内做聚硼硅氧烷的硕博论文很多，
合成步骤与原始数据比期刊论文写得细；中国专利也是这个方向的大头。Claude Science 进不去知网（学校按 IP 授权）。

查证过的现实（2026-10-09，主力机校园网实测）：
  - 学校按出口 IP 授权，不用登录；检索、摘要页、PDF 下载按钮都在。
  - 知网有腾讯拼图验证码（`#tcaptcha_transform_dy`）：平时挂在页面里但移到屏幕外（top=-1000000、透明度 0），
    查得频繁时才挪进屏幕 —— **判断「弹没弹」要看位置和透明度，不能只看元素在不在**（只看在不在会一直误报）。
  - 检索结果页网址不随检索变（前端渲染），翻页只能在结果页上点；所以详情页**在新标签里开、读完就关**，不打乱结果页。
所以这块的形状和 chemdb / polyinfo 一样：**不自己发请求，接管「取全文用的浏览器」里知网的标签**，
**碰到拼图验证码立刻停、回 CAPTCHA_REQUIRED，由人去拖**。这里没有、也不许有任何拖拼图的代码。

⚠ 只读：检索、翻页、读摘要页。**不下载全文**（知网对批量下载封整个学校的出口 IP；要全文请人点「PDF下载」）。
⚠ 频率（间隔、每天上限、缓存）由调用方管（host/mcp/science.py）。

对外接口：
  | 函数 | 说明 |
  |---|---|
  | `search(query, kind='all', sort=None)` | 检索 → 第 1 页（kind：all / journal / thesis / phd / master / conference / patent）|
  | `page(n)` | 结果页上停着的那次检索的第 n 页 |
  | `detail(n=0, url='')` | 结果页第 n 条（或给 url）的摘要页：摘要、关键词、DOI、导师、学科、章节目录、专利主权项…… |
  | `row_url(n)` | 结果页第 n 条的摘要页链接（不导航）|
  | `current()` | 不导航：读知网标签上现在那一页 |
  | `status()` | 标签在不在、验证码挡没挡着 —— 只看浏览器 |
  | `parse_rows` / `parse_detail` / `parse_counts` / `captcha_active` / `kind_selector` | 纯函数（自测覆盖） |

返回 dict：ok, code, kind, count, counts{各库条数}, page, pages, items[], url, why, warnings。
code：OK / NO_RESULTS / CAPTCHA_REQUIRED / NAVIGATE_FAILED / TIMEOUT / NOT_FOUND。
"""
import contextlib
import re
import time

from shared.adapters import pdf_fetch
from shared.kernel.log import get_logger

log = get_logger('cnki')

HOST = 'cnki.net'
HOME = 'https://kns.cnki.net/kns8s/'
# 结果页上切库的标签（a[name=classify]）—— 网站改版只改这里
KINDS = {
    'all': None,
    'journal': 'a[name=classify][resource="JOURNAL"]',
    'thesis': 'a[name=classify][resource="DISSERTATION"]:not([data-chs])',
    'phd': 'a[name=classify][data-chs="CDFD"]',
    'master': 'a[name=classify][data-chs="CMFD"]',
    'conference': 'a[name=classify][resource="CONFERENCE"]:not([data-chs])',
    'patent': 'a[name=classify][data-chs="SCPD"]',
}
SORTS = {'relevance': r'相关度', 'date': r'发表时间|公开日|出版时间|日期', 'cited': r'被引', 'downloads': r'下载'}
_DB_TYPE = {'CDFD': '博士', 'CMFD': '硕士', 'SCPD': '中国专利', 'CJFQ': '期刊', 'CPFD': '会议'}
_TOTAL = re.compile(r'共找到\s*([\d,]+)\s*条结果(?:\s*(\d+)\s*/\s*(\d+))?')   # 只有一页时不带页码


# ══════════════════════════════════════════════════════════════════════
# 纯函数（自测覆盖）
# ══════════════════════════════════════════════════════════════════════

def check_kind(kind):
    kind = (kind or 'all').strip().lower()
    if kind not in KINDS:
        raise ValueError(f'kind 只能是 {" / ".join(KINDS)}（给了「{kind}」）')
    return kind


def kind_selector(kind):
    return KINDS[check_kind(kind)]


def check_sort(sort):
    sort = (sort or '').strip().lower()
    if sort and sort not in SORTS:
        raise ValueError(f'sort 只能是 {" / ".join(SORTS)}（给了「{sort}」）')
    return sort


def captcha_active(geo):
    """拼图验证码弹没弹：geo = 页面上量到的 {top, w, h, op, disp, vis}（没有这个元素给 None）。
    平时它挂在屏幕外（top=-1000000）且透明，挪进屏幕、看得见才算。"""
    if not geo:
        return False
    try:
        top, w, h, op = float(geo.get('top', -1e6)), float(geo.get('w', 0)), float(geo.get('h', 0)), float(geo.get('op', 0))
    except (TypeError, ValueError):
        return False
    return top > -1000 and w > 0 and h > 0 and op > 0 and geo.get('disp') != 'none' and geo.get('vis') != 'hidden'


def parse_total(text):
    """「共找到 498 条结果 1/25」→ (498, 1, 25)；只有一页时页面不写页码：「共找到 4 条结果」→ (4, 1, 1)。读不到 (None, None, None)。"""
    m = _TOTAL.search(text or '')
    if not m:
        return None, None, None
    n = int(m.group(1).replace(',', ''))
    if m.group(2):
        return n, int(m.group(2)), int(m.group(3))
    return n, 1, 1 if n else 0


def _int(s):
    s = re.sub(r'[^\d]', '', s or '')
    return int(s) if s else None


def parse_rows(rows):
    """页面里抽出来的原始行（每行 {cells: [{cls, text, links[]}], href, db, fn}）→ 统一字段。
    期刊 / 学位论文：title, authors, source（刊名或学校）, date, type, cited, downloads；
    专利：title, inventors, applicants, date_applied, date_published, type。"""
    out = []
    for r in rows or []:
        it = {'rank': None, 'title': None, 'url': r.get('href') or None, 'db': r.get('db') or None,
              'filename': r.get('fn') or None}
        dates = []
        for c in r.get('cells') or []:
            cls, text = (c.get('cls') or '').split(' ')[0], (c.get('text') or '').strip()
            links = [x.strip() for x in (c.get('links') or []) if x and x.strip()]
            if cls == 'seq':
                it['rank'] = _int(text)
            elif cls == 'name':
                it['title'] = re.sub(r'\s+', ' ', text).strip() or None
            elif cls in ('author', 'inventor', 'applicant'):
                names = links or [x.strip() for x in re.split(r'[;；]', text) if x.strip()]
                it[{'author': 'authors', 'inventor': 'inventors', 'applicant': 'applicants'}[cls]] = names
            elif cls in ('source', 'unit'):        # 博士 / 硕士单库的表里「学位授予单位」列叫 unit
                it['source'] = text or None
            elif cls == 'date':
                dates.append(text or None)
            elif cls == 'data':
                it['type'] = text or None
            elif cls == 'quote':
                it['cited'] = _int(text) or 0
            elif cls == 'download':
                it['downloads'] = _int(text)
        if not it.get('type') and it.get('db') in _DB_TYPE:     # 单库的表没有「类型」列，按库名补
            it['type'] = _DB_TYPE[it['db']]
        if 'inventors' in it or 'applicants' in it or (it.get('type') or '').endswith('专利'):
            it['date_applied'] = dates[0] if dates else None
            it['date_published'] = dates[1] if len(dates) > 1 else None
            if it.get('filename'):
                it['patent_no'] = it['filename']
        else:
            it['date'] = dates[0] if dates else None
        if it['title']:
            out.append(it)
    return out


def parse_counts(tabs):
    """切库标签 [{name, n, chs, res}] → {期刊: 47, 学位论文: 34, 博士: 4, …}（空的不给）。"""
    out = {}
    for t in tabs or []:
        name = (t.get('name') or '').strip()
        n = _int(t.get('n'))
        if name and n is not None and name not in out:
            out[name] = n
    return out


_DETAIL_KEYS = ('摘要', '关键词', '基金资助', 'DOI', '专辑', '专题', '分类号', '导师', '学科专业', '在线公开时间',
                '申请号', '申请日', '公开号', '公开日', '申请人', '地址', '发明人', '代理机构', '代理人', '主分类号',
                '国省代码', '页数', '主权项', '优先权', '法律状态')


def parse_detail(text):
    """摘要页文字 → {title, authors_line, institution, fields{摘要、关键词、DOI、导师……}, outline[]}。
    学位论文的「目录」原样按行给（带缩进层级）。"""
    lines = [ln.rstrip() for ln in (text or '').splitlines()]
    fields, key = {}, None
    for ln in lines:
        s = ln.strip()
        m = re.match(r'^([一-龥A-Za-z]{2,8})[：:]\s*(.*)$', s)
        if m and m.group(1) in _DETAIL_KEYS:
            key = m.group(1)
            fields[key] = m.group(2).strip()
            continue
        if key and s and key in ('摘要', '主权项') and not re.match(r'^[一-龥A-Za-z]{2,8}[：:]', s):
            if s in ('更多', '收起'):
                continue
            fields[key] = (fields[key] + ' ' + s).strip()
            continue
        key = None
    for k in ('摘要', '主权项'):
        if k in fields:
            fields[k] = re.sub(r'\s*\.\.\.\s*更多$|\s*更多$', '', fields[k]).strip()
    if '关键词' in fields:
        fields['关键词'] = [x.strip() for x in re.split(r'[;；]', fields['关键词']) if x.strip()]
    # 目录在页面最前面：「文章目录」之后，到 AI 提问（以「？」结尾的句子）/ 服务推荐为止（2026-10-09 实测）
    outline = []
    i = next((j for j, ln in enumerate(lines) if ln.strip() in ('文章目录', '目录')), None)
    if i is not None:
        for ln in lines[i + 1:]:
            s = ln.replace('\xa0', ' ').replace('\t', '    ').rstrip()
            if not s.strip():
                continue
            if s.strip() in ('服务推荐', '推广 X') or s.strip().endswith('？') or re.match(r'^\s*摘要[：:]', s):
                break
            outline.append(s)
    # 标题 / 作者 / 学校 = 「摘要：」那一行之前最后三行非空的（「文章目录」下面也有一行「摘要」，别认错）
    head = None
    idx = next((j for j, ln in enumerate(lines) if re.match(r'^\s*摘要[：:]', ln)), None)
    if idx and idx >= 3:
        head = [h for h in (ln.replace('\xa0', ' ').strip() for ln in lines[max(0, idx - 8):idx]) if h]
    out = {'fields': fields, 'outline': outline[:300]}
    if head:
        out['title'], out['authors_line'] = head[-3] if len(head) >= 3 else None, head[-2] if len(head) >= 2 else None
        out['institution'] = head[-1]
    return out


def _result(**kw):
    r = {'ok': False, 'code': 'OK', 'kind': None, 'count': None, 'counts': {}, 'page': None, 'pages': None,
         'items': [], 'url': '', 'why': '', 'warnings': []}
    r.update(kw)
    return r


# ══════════════════════════════════════════════════════════════════════
# 浏览器
# ══════════════════════════════════════════════════════════════════════

_CAP_JS = """() => { const e = document.getElementById('tcaptcha_transform_dy'); if (!e) return null;
  const r = e.getBoundingClientRect(), s = getComputedStyle(e);
  return {top: r.top, w: r.width, h: r.height, op: s.opacity, disp: s.display, vis: s.visibility}; }"""

_ROWS_JS = """() => [...document.querySelectorAll('table.result-table-list tbody tr')].map(tr => {
  const c = tr.querySelector('a.icon-collect');
  return {href: (tr.querySelector('td.name a') || {}).href || null,
          db: c ? c.getAttribute('data-dbname') : null, fn: c ? c.getAttribute('data-filename') : null,
          cells: [...tr.querySelectorAll('td')].map(td => ({cls: td.className, text: td.innerText || '',
                    links: [...td.querySelectorAll('a')].map(a => a.innerText)}))};
})"""

_TABS_JS = """() => [...document.querySelectorAll('a[name=classify]')].map(a => ({
  name: (a.querySelector('span') || {}).innerText, n: (a.querySelector('em') || {}).innerText,
  chs: a.getAttribute('data-chs'), res: a.getAttribute('resource')}))"""


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
    mine = [p for p in ctx.pages if 'kns.cnki.net/kns' in (p.url or '')]
    return mine[-1] if mine else None


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
    except Exception as e:
        log.warn(f'后台开标签失败（{str(e)[:80]}），退回前台开法')
        return ctx.new_page()


def _tab(browser, ctx):
    return _find_tab(ctx) or _new_tab(browser, ctx)


def _body(pg):
    try:
        return pg.evaluate('document.body ? document.body.innerText : ""') or ''
    except Exception:
        return ''


def _captcha(pg):
    try:
        return captcha_active(pg.evaluate(_CAP_JS))
    except Exception:
        return False


def _gate(pg, warnings):
    if _captcha(pg):
        return _result(code='CAPTCHA_REQUIRED', url=pg.url, warnings=warnings,
                       why='知网弹了拼图验证码：请人在主力机「取全文用的浏览器」的知网标签里把拼图拖到位，'
                           '之后用 cnki_current 读这一页（不用重查）')
    return None


def _settle(pg, ready, timeout=40):
    end, prev = time.time() + timeout, -1
    while time.time() < end:
        if _captcha(pg):
            return True
        t = _body(pg)
        if ready(t) and len(t) == prev:
            return True
        prev = len(t)
        pg.wait_for_timeout(1200)
    return False


def _rows_result(pg, kind, warnings):
    t = _body(pg)
    total, cur, pages = parse_total(t)
    items = parse_rows(pg.evaluate(_ROWS_JS))
    counts = parse_counts(pg.evaluate(_TABS_JS))
    code = 'OK' if items else 'NO_RESULTS'
    return _result(ok=True, code=code, kind=kind, count=total, counts=counts, page=cur, pages=pages,
                   page_size=len(items), items=items, url=pg.url, warnings=warnings)


def _sort(pg, sort, warnings):
    pat = SORTS[sort]
    got = pg.evaluate("""(pat) => { const re = new RegExp(pat); const li = [...document.querySelectorAll('#orderList li')]
        .find(x => re.test(x.innerText || '')); if (!li) return null; (li.querySelector('a') || li).click(); return li.innerText.trim(); }""", pat)
    if not got:
        warnings.append(f'sort_unavailable: 这个库的排序里没有「{sort}」')
        return False
    return True


def search(query, kind='all', sort=None):
    """检索一次 → 结果第 1 页。query = 检索词（中文或英文，按「主题」检索，同知网首页的默认）；
    kind = all / journal / thesis（博硕都要）/ phd / master / conference / patent（中国专利）；
    sort = relevance / date / cited / downloads（专利没有被引、下载）。"""
    query = (query or '').strip()
    if not query:
        raise ValueError('query 不能空')
    kind = check_kind(kind)
    sort = check_sort(sort)
    warnings = []
    with _session() as (browser, ctx):
        pg = _tab(browser, ctx)
        if pg.url and HOST in pg.url:
            bad = _gate(pg, warnings)
            if bad:
                return bad
        try:
            pg.goto(HOME, wait_until='load', timeout=60000)
        except Exception as e:
            return _result(code='NAVIGATE_FAILED', url=pg.url, warnings=warnings, why=f'打不开知网首页：{str(e)[:120]}')
        _settle(pg, lambda t: True, timeout=8)
        bad = _gate(pg, warnings)
        if bad:
            return bad
        try:
            pg.fill('#txt_search', query)
            pg.click('input.search-btn')
        except Exception as e:
            return _result(code='NAVIGATE_FAILED', url=pg.url, warnings=warnings, why=f'首页检索框没找到（改版了？）：{str(e)[:100]}')
        if not _settle(pg, lambda t: bool(_TOTAL.search(t)) or '暂无数据' in t, timeout=45):
            return _gate(pg, warnings) or _result(code='TIMEOUT', url=pg.url, warnings=warnings, why='结果 45 秒没出来')
        bad = _gate(pg, warnings)
        if bad:
            return bad
        sel = KINDS[kind]
        if sel:
            before = parse_total(_body(pg))[0]
            ok = pg.evaluate('(s) => { const a = document.querySelector(s); if (!a) return false; a.click(); return true; }', sel)
            if not ok:
                return _result(code='NOT_FOUND', url=pg.url, warnings=warnings, why=f'结果页上没有「{kind}」这个库的标签')
            pg.wait_for_timeout(1500)
            _settle(pg, lambda t: bool(_TOTAL.search(t)) and parse_total(t)[0] != before or '暂无数据' in t, timeout=40)
            bad = _gate(pg, warnings)
            if bad:
                return bad
        if sort and _sort(pg, sort, warnings):
            pg.wait_for_timeout(2500)
            _settle(pg, lambda t: bool(_TOTAL.search(t)), timeout=30)
            bad = _gate(pg, warnings)
            if bad:
                return bad
        r = _rows_result(pg, kind, warnings)
        r['query'] = query
        r['sort'] = sort or 'relevance'
        return r


def page(n):
    """结果页上停着的那次检索的第 n 页（点页码；跳得远时点「下一页」凑不到就报 NOT_FOUND）。"""
    n = int(n)
    warnings = []
    with _session() as (browser, ctx):
        pg = _find_tab(ctx)
        if not pg or not _TOTAL.search(_body(pg)):
            return _result(code='NOT_FOUND', why='知网标签上没有停着的检索结果，先 search')
        bad = _gate(pg, warnings)
        if bad:
            return bad
        total, cur, pages = parse_total(_body(pg))
        if pages and n > pages:
            return _result(code='NOT_FOUND', why=f'一共只有 {pages} 页')
        if cur == n:
            return _rows_result(pg, None, warnings)
        ok = pg.evaluate("""(n) => { const a = [...document.querySelectorAll('.pages a, #countPageDiv a, a')].find(x => (x.innerText || '').trim() === String(n));
            if (!a) return false; a.click(); return true; }""", n)
        if not ok:
            return _result(code='NOT_FOUND', url=pg.url, warnings=warnings, why=f'分页条上没有第 {n} 页的链接（只显示附近几页）')
        _settle(pg, lambda t: parse_total(t)[1] == n, timeout=40)
        return _gate(pg, warnings) or _rows_result(pg, None, warnings)


def detail(n=0, url=''):
    """结果页第 n 条（rank，从 1 数）或给定 url 的摘要页。在新标签里开、读完就关，结果页不动。"""
    warnings = []
    with _session() as (browser, ctx):
        if not url:
            pg = _find_tab(ctx)
            if not pg:
                return _result(code='NOT_FOUND', why='知网标签上没有检索结果，先 search 或直接给 url')
            items = parse_rows(pg.evaluate(_ROWS_JS))
            hit = next((it for it in items if it.get('rank') == int(n)), None)
            if not hit or not hit.get('url'):
                return _result(code='NOT_FOUND', why=f'这一页没有第 {n} 条（本页 rank：{[it.get("rank") for it in items][:3]}…）')
            url = hit['url']
        if 'cnki.net' not in url:
            raise ValueError('url 要是知网的摘要页（kns.cnki.net/kcms2/…）')
        tab = _new_tab(browser, ctx)
        keep = False          # 撞验证码时这个标签留给人拖；其余情况读完就关
        try:
            try:
                tab.goto(url, wait_until='load', timeout=60000)
            except Exception as e:
                return _result(code='NAVIGATE_FAILED', url=url, warnings=warnings, why=f'打不开摘要页：{str(e)[:120]}')
            _settle(tab, lambda t: '摘要' in t or '主权项' in t, timeout=40)
            if _captcha(tab):
                keep = True   # 人拖完后 current() 会读到它（它是最后一个知网标签）
                return _result(code='CAPTCHA_REQUIRED', url=tab.url, warnings=warnings,
                               why='知网摘要页弹了拼图验证码：请人在主力机浏览器里拖好，之后用 cnki_current 读')
            got = parse_detail(_body(tab))
            return _result(ok=True, code='OK' if got['fields'] else 'NO_RESULTS', url=url, warnings=warnings, detail=got)
        finally:
            if not keep:
                try:
                    tab.close()
                except Exception:
                    pass


def row_url(n):
    """结果页上第 n 条（rank）的摘要页链接；不导航、不碰网站。没有返回 None。"""
    with _session() as (browser, ctx):
        pg = _find_tab(ctx)
        if not pg:
            return None
        hit = next((it for it in parse_rows(pg.evaluate(_ROWS_JS)) if it.get('rank') == int(n)), None)
        return (hit or {}).get('url')


def current():
    """不导航：读知网最新那个标签现在的页面（结果页按列表解析，摘要页按详情解析）。"""
    warnings = []
    with _session() as (browser, ctx):
        tabs = [p for p in ctx.pages if HOST in (p.url or '')]
        if not tabs:
            return _result(code='NOT_FOUND', why='浏览器里没有知网的标签')
        pg = tabs[-1]
        bad = _gate(pg, warnings)
        if bad:
            return bad
        if '/kcms' in (pg.url or ''):
            got = parse_detail(_body(pg))
            return _result(ok=True, code='OK', url=pg.url, warnings=warnings, detail=got)
        if _TOTAL.search(_body(pg)):
            return _rows_result(pg, None, warnings)
        return _result(ok=True, code='OK', url=pg.url, warnings=warnings, why='这一页不是结果页也不是摘要页')


def status():
    """知网标签在不在、停在哪、验证码挡没挡着 —— 只看浏览器，不碰网站。"""
    with _session() as (browser, ctx):
        tabs = [p for p in ctx.pages if HOST in (p.url or '')]
        if not tabs:
            return {'tab_open': False, 'url': '', 'captcha': False, 'on_results': False}
        pg = tabs[-1]
        return {'tab_open': True, 'url': pg.url, 'captcha': _captcha(pg),
                'on_results': bool(_TOTAL.search(_body(pg))), 'tabs': len(tabs)}
