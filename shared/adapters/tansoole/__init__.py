# -*- coding: utf-8 -*-
"""tansoole · 探索平台（泰坦科技，用户平时买药品的地方）—— 借人已经登录好的浏览器读搜索结果页

**为什么有这块（2026-10-11 用户定）**：Claude Science 设计实验时要知道药品在他实际采购的平台上
有哪些品牌、规格、纯度、要等多久（现货 / 几个工作日 / 期货），才能判断「会不会卡在一个要等 40 天的药上、
有没有现货的替代品牌」。价格另走 SciFinder 的供应商页（chemdb kind=suppliers）。

查证过的现实（2026-10-11）：
  - 没有公开的程序接口；交易条款、注册页里没找到禁止程序访问的原文。
  - **价格两栏（市场价 / 探索价）是用特制字体打乱的**（页面文字是 ɎŁŵ 这类乱码，人眼看是数字）——
    网站专门防程序抄价格。用户知情后定：**价格一律不读**。每行「复制」按钮里藏着明文价格，同样不读。
    这块里没有、也不许加任何读价格栏、解字体、读复制按钮的代码。
所以形状同 chemdb / polyinfo：**不自己发请求，接管主力机上那个「取全文用的浏览器」**，人在里面登录过一次，
按人的频率搜、读结果页的明文栏。

⚠ 只读：搜索、翻页、读列表。不加购物车、不询价、不下单、不登录。
⚠ 频率（间隔、每天上限、缓存）由调用方（host/mcp/science.py）管。

对外接口：
  | 函数 | 说明 |
  |---|---|
  | `search(query)` | 搜一次（CAS 号 / 中英文名 / 货号）→ 第 1 页（每页调到 100 条） |
  | `page(n)` | 当前搜索的第 n 页 |
  | `status()` | 标签在不在、登没登录 —— 只看浏览器，不碰网站 |
  | `parse_spec` / `parse_lead` / `norm_row` / `summarize` | 纯函数（自测覆盖） |

返回 dict：ok, code, complete, warnings, query, page, pages, page_size, count, logged_in, compounds[], items[], summary,
other_categories, url, why。code：OK / NO_RESULTS / NO_SEARCH / CAPTCHA_REQUIRED / NAVIGATE_FAILED / TIMEOUT。
"""
import contextlib
import re
import time
import urllib.parse

from shared.adapters import pdf_fetch
from shared.kernel.log import get_logger

log = get_logger('tansoole')

HOST = 'tansoole.com'
HOME = 'https://www.tansoole.com/index.html'
SEARCH_URL = 'https://www.tansoole.com/search/search.htm?gloabSearchVo.queryString={q}'
PAGE_SIZE = 100            # 网站可选 50 / 100 / 300；100 一页够装下大多数单个化合物（苯硼酸 55 条）

# ══════════════════════════════════════════════════════════════════════
# 纯函数（自测覆盖）
# ══════════════════════════════════════════════════════════════════════

_UNITS = {'mg': 'mg', 'g': 'g', 'gr': 'g', 'kg': 'kg', 'ml': 'mL', 'l': 'L', 'ul': 'µL', 'µl': 'µL', 'μl': 'µL', 'ug': 'µg',
          'µg': 'µg', 'μg': 'µg', 't': 't'}
_TO_G = {'mg': 0.001, 'g': 1, 'kg': 1000, 'µg': 1e-6, 't': 1e6}


def parse_spec(s):
    """规格「5g」「100G」「10GR」「2.5kg」「500ML」→ {qty, unit, grams}；认不出（「1支」「10mM*1mL」）→ {text}。"""
    s = (s or '').strip()
    m = re.match(r'^(\d+(?:\.\d+)?)\s*([a-zA-Zµμ]+)$', s)
    unit = _UNITS.get(m.group(2).lower()) if m else None
    if not m or not unit:
        return {'text': s} if s else {}
    qty = float(m.group(1))
    out = {'qty': int(qty) if qty.is_integer() else qty, 'unit': unit}
    if unit in _TO_G:
        out['grams'] = round(qty * _TO_G[unit], 6)
    return out


def parse_lead(s):
    """货期「现货」「7-10个工作日」「1-2个工作日 (以Sigma库存为准)」「期货」→ {in_stock, lead_days, futures, note}。"""
    s = re.sub(r'\s+', ' ', (s or '')).strip()
    note = (re.search(r'[(（]([^)）]+)[)）]', s) or [None, None])[1]
    core = re.sub(r'[(（][^)）]*[)）]', '', s).replace('特价', '').strip()
    out = {'in_stock': '现货' in core, 'futures': '期货' in core, 'lead_days': None}
    m = re.search(r'(\d+)\s*(?:-|~|～|—)\s*(\d+)\s*个?工作日', core) or re.search(r'(\d+)\s*个?工作日', core)
    if m:
        out['lead_days'] = [int(m.group(1)), int(m.group(m.lastindex or 1))]
    if note:
        out['note'] = note
    return out


def norm_row(x, rank=None):
    """页面抽出的一行（只有明文栏）→ 统一字段。"""
    lead_text = re.sub(r'\s+', ' ', ' '.join(t for t in (x.get('lead'), x.get('lead_note')) if t)).strip()
    out = {'rank': rank, 'product_no': (x.get('product_no') or '').strip() or None,
           'brand': (x.get('brand') or '').strip() or None, 'catalog_no': (x.get('catalog_no') or '').strip() or None,
           'spec': (x.get('spec') or '').strip() or None, **{k: v for k, v in parse_spec(x.get('spec')).items() if k != 'text'},
           'purity': (x.get('param') or '').strip() or None, 'grade': (x.get('grade') or '').strip() or None,
           'lead_time': lead_text or None, **parse_lead(lead_text),
           'action': (x.get('action') or '').strip() or None,       # 购买 = 直接下单；询价 = 要问价（多为期货）
           'compound': x.get('compound')}
    if x.get('special'):
        out['on_sale'] = True                                     # 页面上标了「特价」
    if x.get('url'):
        out['url'] = urllib.parse.urljoin('https://www.tansoole.com/', x['url'])
    return out


def summarize(items):
    """一页 → 一眼看得出的：有哪些品牌、几条现货、现货里各品牌最大包装、最快的非现货要几天。"""
    brands = {}
    for it in items:
        b = it.get('brand') or '?'
        d = brands.setdefault(b, {'n': 0, 'in_stock': 0, 'purities': [], 'max_stock_grams': None})
        d['n'] += 1
        if it.get('in_stock'):
            d['in_stock'] += 1
            g = it.get('grams')
            if g is not None and (d['max_stock_grams'] is None or g > d['max_stock_grams']):
                d['max_stock_grams'] = g
        if it.get('purity') and it['purity'] not in d['purities']:
            d['purities'].append(it['purity'])
    leads = [it['lead_days'][1] for it in items if it.get('lead_days') and not it.get('in_stock')]
    return {'n_items': len(items), 'n_in_stock': sum(1 for it in items if it.get('in_stock')),
            'n_futures': sum(1 for it in items if it.get('futures')),
            'brands': dict(sorted(brands.items(), key=lambda kv: (-kv[1]['in_stock'], -kv[1]['n']))),
            'fastest_non_stock_days': min(leads) if leads else None}


def parse_count(s):
    m = re.search(r'共\s*([\d,]+)\s*条', s or '')
    return int(m.group(1).replace(',', '')) if m else None


def _result(**kw):
    r = {'ok': False, 'code': 'OK', 'complete': True, 'warnings': [], 'query': None, 'page': 0, 'pages': None,
         'page_size': None, 'count': None, 'logged_in': None, 'compounds': [], 'items': [], 'url': '', 'why': ''}
    r.update(kw)
    return r


# ══════════════════════════════════════════════════════════════════════
# 浏览器
# ══════════════════════════════════════════════════════════════════════
# 自己连（同 chemdb / polyinfo）：不借 pdf_fetch._connect —— 那个会清扫多余标签。每次调用连上、用完就断。
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
                f'连不上主力机的「取全文用的浏览器」（{target}）：{e}。它要开着，探索平台要在里面登录过。')
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        yield browser, ctx
    finally:
        try:
            pw.stop()                     # 只断开连接，不关浏览器、不关标签
        except Exception:
            pass


def _find_tab(ctx):
    mine = [p for p in ctx.pages if HOST in (p.url or '')]
    return mine[-1] if mine else None


def _tab(browser, ctx):
    """探索平台专用的标签：已有就复用（登录状态在上面），没有就后台开一个。"""
    pg = _find_tab(ctx)
    if pg:
        return pg
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


def _logged_in(text):
    return '退出登录' in (text or '')[:4000]


def _is_captcha(text):
    """人机验证页：正文短、出现验证字样、没有结果表。没见过真样子（2026-10-11 未撞上），宁可多判。"""
    t = text or ''
    return bool(re.search(r'安全验证|人机验证|滑动.{0,6}验证|请完成验证|验证码', t)) and '产品编号' not in t


def _settle(pg, timeout=40):
    """等结果表出来、或「共 N 条」、或明显没结果，且正文长度两次不变 → 是否等到。"""
    end, prev = time.time() + timeout, -1
    while time.time() < end:
        t = _body(pg)
        ready = parse_count(t) is not None or re.search(r'没有找到|抱歉|无相关', t) or _is_captcha(t)
        if ready and len(t) == prev:
            return True
        prev = len(t)
        pg.wait_for_timeout(1200)
    return False


# ── 页面里跑的抽取脚本：**只读明文栏**。价格栏（li.row05）与「复制」按钮（藏着明文价格）一律不碰 ──
_ROWS_JS = r"""() => {
  const T = e => e ? (e.innerText || '').replace(/\s+/g, ' ').trim() : '';
  const out = {compounds: [], rows: []};
  let cur = null;
  // 页面上有两个 .product-show，第一个是空的（2026-10-11 实测）—— 挑装着结果行的那个
  const box = [...document.querySelectorAll('.product-show')].find(e => e.querySelector('ul.show-list-con')) || document.body;
  box.querySelectorAll('.list-reagent-info, ul.show-list.show-list-con').forEach(el => {
    if (el.classList.contains('list-reagent-info')) {
      const lis = [...el.querySelectorAll('dd li')];
      // 几个 span 挨着、中间没空格（innerText 会连成「98-80-6MDL号：…」，2026-10-11 实测）—— 逐个取再用 | 隔开
      const mes = [...el.querySelectorAll('li.mes > span')].map(T).join(' | ');
      const g = re => (mes.match(re) || [])[1] || null;
      cur = {name_cn: T(el.querySelector('li.name')) || null, name_en: lis[1] ? T(lis[1]) : null,
             cas_rn: g(/CAS号：\s*([^\s|]+)/), mdl: g(/MDL号：\s*([^\s|]+)/), formula: g(/分子式：\s*([^\s|]+)/), mw: g(/分子量：\s*([\d.]+)/)};
      out.compounds.push(cur);
      return;
    }
    const li = sel => el.querySelector(sel);
    const cols = [...el.children].filter(c => c.tagName === 'LI');
    const a = li('li.row04 a');
    const act = li('li.row03 a.btn-list-buy');
    out.rows.push({product_no: T(a), url: a ? a.getAttribute('href') : null,
      catalog_no: cols[1] ? (cols[1].getAttribute('title') || T(cols[1])) : null, brand: cols[2] ? T(cols[2]) : null,
      spec: T(li('li.attrrow15')), param: T(li('li.parameterrow15')), grade: cols[5] ? T(cols[5]) : null,
      special: /特价/.test(T(li('li.row07'))), lead: T(li('li.row06')),
      action: act ? T(act) : null, compound: cur ? (cur.cas_rn || cur.name_cn) : null});
  });
  const others = document.querySelector('.pro-show-search-other-list');
  return {compounds: out.compounds, rows: out.rows, others: others ? T(others).replace(/^继续搜索其它品类:\s*/, '') : null,
          count: T(document.querySelector('.layui-laypage-count')),
          size: (document.querySelector('.layui-laypage-limits select') || {}).value || null,
          cur: T(document.querySelector('.layui-laypage-curr'))};
}"""


def _set_page_size(pg, n=PAGE_SIZE):
    """每页条数调到 n（网站会重画列表）。已经是就不动。→ 现在的每页条数。"""
    try:
        got = pg.evaluate("""(n) => { const s = document.querySelector('.layui-laypage-limits select');
            if (!s) return null; if (s.value === String(n)) return +s.value;
            s.value = String(n); s.dispatchEvent(new Event('change', {bubbles: true})); return -1; }""", n)
    except Exception:
        return None
    if got == -1:
        pg.wait_for_timeout(2000)
        _settle(pg)
        return n
    return got


def _extract(pg, query, warnings, page_no=None):
    text = _body(pg)
    if _is_captcha(text):
        return _result(code='CAPTCHA_REQUIRED', url=pg.url, query=query, warnings=warnings, complete=False,
                       why='探索平台弹了验证：请人在主力机「取全文用的浏览器」的探索平台标签里完成验证，再重查')
    d = pg.evaluate(_ROWS_JS)
    r = _result(ok=True, url=pg.url, query=query, warnings=warnings, logged_in=_logged_in(text))
    r['count'] = parse_count(d.get('count')) or parse_count(text)
    r['page_size'] = int(d['size']) if (d.get('size') or '').isdigit() else None
    r['page'] = page_no or (int(d['cur']) if (d.get('cur') or '').isdigit() else 1)
    if r['count'] and r['page_size']:
        r['pages'] = -(-r['count'] // r['page_size'])
    base = (r['page'] - 1) * (r['page_size'] or 0)
    r['compounds'] = d.get('compounds') or []
    r['items'] = [norm_row(x, base + i + 1) for i, x in enumerate(d.get('rows') or [])]
    r['summary'] = summarize(r['items'])
    if d.get('others'):
        r['other_categories'] = d['others']          # 「抑制剂・激动剂2条, 分析试剂·标准品11条」—— 别的品类里还有
    r['note'] = '价格不读（网站用特制字体防程序抄价格）；价格查 SciFinder：chemdb_search kind=suppliers'
    if not r['items'] and r['count']:
        # 页面说有 N 条却一行没读出来 = 页面改版或还没画完；不当「没结果」（会被缓存一整天，2026-10-11 踩过）
        r.update(code='TIMEOUT', complete=False, why=f'页面显示 {r["count"]} 条，但一行也没读出来（页面可能改版了）')
        r['warnings'].append('no_items_parsed')
    elif not r['items']:
        r.update(code='NO_RESULTS', why='探索平台里没搜到（换中文名 / 英文名 / CAS 号试试）')
    if r['logged_in'] is False:
        r['warnings'].append('not_logged_in: 探索平台标签没登录，货期可能不全；请人在主力机浏览器里登录')
    return r


# ══════════════════════════════════════════════════════════════════════
# 对外
# ══════════════════════════════════════════════════════════════════════

def search(query):
    """搜一次（CAS 号 / 中英文名 / 货号），读第 1 页（每页调到 100 条）。"""
    query = (query or '').strip()
    if not query:
        raise ValueError('query 不能空')
    log.info(f'探索平台 搜索：{query}')
    warnings = []
    with _session() as (browser, ctx):
        pg = _tab(browser, ctx)
        try:
            try:
                pg.goto(SEARCH_URL.format(q=urllib.parse.quote(query)), wait_until='domcontentloaded', timeout=60000)
            except Exception as e:
                return _result(code='NAVIGATE_FAILED', url=pg.url, query=query, why=f'打不开搜索页：{str(e)[:120]}')
            ok = _settle(pg)
            if (parse_count(_body(pg)) or 0) > 50:
                _set_page_size(pg)
            r = _extract(pg, query, warnings, page_no=1)
            if not ok and r['code'] == 'OK':
                r.update(code='TIMEOUT', complete=False, why='列表页还在加载，读到的可能不全')
            return r
        except Exception as e:
            log.warn(f'探索平台 搜索出错：{type(e).__name__}: {str(e)[:200]}')
            return _result(code='TIMEOUT', complete=False, url=getattr(pg, 'url', ''), query=query,
                           why=f'{type(e).__name__}: {str(e)[:200]}')


def page(n):
    """当前搜索的第 n 页（用页面底下的「到第 N 页」）。"""
    n = int(n)
    if n < 1:
        raise ValueError('页码从 1 开始')
    with _session() as (browser, ctx):
        pg = _find_tab(ctx)
        if not pg or '/search/' not in (pg.url or ''):
            return _result(code='NO_SEARCH', url=pg.url if pg else '', why='探索平台标签上没有搜索结果，先 search')
        q = (urllib.parse.parse_qs(urllib.parse.urlparse(pg.url).query).get('gloabSearchVo.queryString') or [''])[0]
        box = pg.locator('.layui-laypage-skip input')
        if not box.count():
            return _result(code='NO_RESULTS', url=pg.url, query=q, why='只有一页')
        box.first.fill(str(n))
        pg.locator('.layui-laypage-skip button').first.click()
        pg.wait_for_timeout(2000)
        ok = _settle(pg)
        r = _extract(pg, q, [], page_no=n)
        if not ok and r['code'] == 'OK':
            r.update(code='TIMEOUT', complete=False, why='列表页还在加载，读到的可能不全')
        return r


def status():
    """标签在不在、登没登录、停在搜索结果上没有 —— 只看浏览器，不碰网站。"""
    with _session() as (browser, ctx):
        pg = _find_tab(ctx)
        if not pg:
            return {'tab_open': False, 'logged_in': None, 'url': ''}
        t = _body(pg)
        return {'tab_open': True, 'logged_in': _logged_in(t), 'captcha': _is_captcha(t), 'url': pg.url,
                'on_results': '/search/' in (pg.url or '')}
