# -*- coding: utf-8 -*-
"""chemdb · 化学数据库（SciFinder / Reaxys）检索 —— 借人已经登录好的浏览器读结果页

**为什么有这块（2026-10-08 用户定）**：SciFinder、Reaxys 一搜就是几十上百条文献和专利，
人一条条点开筛很费时间；Claude Science 读得快，但它进不去（要学校订阅 + 个人登录）。

查证过的现实（2026-10-08）：
  - SciFinder 的官方接口只给合作软件（电子实验记录本），搜索只回一个「去网页看」的链接，
    登录必须人在浏览器前 —— 不是给程序取数据用的。
  - Reaxys 有真数据接口，但要单位另外订接口，网页订阅不含。
所以这块的形状和 pdf_fetch 一样：**不自己发请求，接管主力机上那个「取全文用的浏览器」**，
人在里面登录一次（SciFinder 个人账号、Reaxys 机构登录），之后按人的频率搜、读结果页。

⚠ 只读：搜索、筛选、排序、翻页、读列表。**不导出、不批量点详情、不登录**（登录永远是人做）。
⚠ 频率（每次间隔、每天上限、缓存）由调用方管（host/mcp/science.py），这块只管「怎么在页面上搜」。
⚠ 结果页是前端渲染的：等到列表条目出现、数目不再变才读；库自带的 AI 摘要还在生成就标出来。

对外接口：
  | 函数 | 说明 |
  |---|---|
  | `search(db, query='', kind='references', structure='', match='exact', sort=None, filters=None, mode='auto', raw=False)` | 搜一次 → 第 1 页 |
  | `page(db, n, base_url='', raw=False)` | 结果列表第 n 页（base_url = 那次搜索回的 url；不给就用标签上停着的） |
  | `tabs()` | 两个库的标签在不在、停在不在登录页 —— 只看浏览器，不碰网站 |
  | `page_url` / `page_no` / `is_login` / `clean_text` / `count_of` / `parse_sf_bib` / `norm_rx_item` | 纯函数（自测覆盖） |

检索三种入口（2026-10-08 用户：「最常用的是 CAS 号查精确结构、画大致结构查」）：
  - 关键词：query='boron siloxane self-healing'
  - CAS 号：query='98-80-6' —— kind=substances 回物质；kind=references 先落到这个物质，再跳「用了它的文献 / 专利」
  - 结构式：structure='OB(O)c1ccccc1'（SMILES；Reaxys 也收 molfile）+ match=exact / substructure / similarity
    SciFinder 走 CAS Draw 的「Add to editor」，Reaxys 走 MarvinJS 的 importStructure —— 两个库的搜索框都不能直接收 SMILES
    （SciFinder 的框收了会当按原样结构搜，Reaxys 的框收了会当关键词去标题里找字面，2026-10-08 实测）。

返回 dict：ok, code, complete, warnings, db, kind, query, query_interpretation, page, page_size, pages,
count, items[], facets{}, ai_summary, preview（Reaxys 的子检索拆分）, url, title, text（raw=True 才有）, why。
code：OK / LOGIN_REQUIRED（人去浏览器登录）/ NO_RESULTS / NO_SEARCH（翻页前没搜过）/
NAVIGATE_FAILED / TIMEOUT。只有「浏览器连不上 / 没装 playwright」才抛异常（沿用 pdf_fetch 的两个异常）。
"""
import contextlib
import re
import time
import urllib.parse

from shared.adapters import pdf_fetch
from shared.kernel.log import get_logger

log = get_logger('chemdb')

DBS = ('scifinder', 'reaxys')
KINDS = ('references', 'substances', 'reactions')
MATCHES = ('exact', 'substructure', 'similarity')
CAS_RN_RE = re.compile(r'^\d{2,7}-\d{2}-\d$')
# 实测（2026-10-08）SciFinder 的选项：Relevance / Times Cited / Accession Number: … / Publication Date: Newest / Oldest
SORTS = {'relevance': r'relevan', 'date': r'newest|latest|publication (date|year)|^year|^date',
         'cited': r'times cited|cited|citation'}

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
        'item': '.reference-data, .substance-tile',
        'match_btn': '.structure-match-select',
        'match_label': {'exact': 'As Drawn', 'substructure': 'Substructure', 'similarity': 'Similarity'},
        'draw_type': {'references': '#result-type-reference', 'substances': '#result-type-substance',
                      'reactions': '#result-type-reaction'},
        'original': '.search-original-query-button',
        'sort': 'button[aria-label="Sort"]',
    },
    'reaxys': {
        'host': 'reaxys.com',
        'home': 'https://www.reaxys.com/#/search/quick/query',
        'input': '#id-quick-search-input',
        'view_results': '.e2e-view-results',
        'card_word': {'references': 'documents', 'substances': 'substances', 'reactions': 'reactions'},
        # 结果页网址：…/list/<uuid>/<页码>/desc/…
        'page_re': r'(/list/[^/]+/)(\d+)(/)',
        'login_re': r'#/login|id\.elsevier\.com',
        'item': 'ul.e2e-results-list > li',
        'page_size': '[role=combobox][aria-label="Results per page"]',
        'match_label': {'exact': 'As drawn', 'substructure': 'As substructure', 'similarity': 'Similar'},
        # 快速检索框旁边的三个按钮（data-e2e 比文字稳：挂着结构时按钮文字会带别的东西，2026-10-08 实测 text-is 找不到）
        'clear_structure': '[data-e2e="e2e-build-query-structureDrawing-clear-button"]',
        'draw': '[data-e2e="e2e-build-query-structuredrawing-draw"]',
        'search': '[data-e2e="search query"], [data-testid="search query"]',
        'sort': 'button[aria-label^="Select sorting category"]',
    },
}

# 每页都有、对判断没用的行
_BOILER = re.compile(
    r'^(Skip to .*|Copyright ©.*|All content on this site:.*|We use cookies.*|Cookie Settings|'
    r'Help Contact Us Legal|Elsevier|RELX™|Feedback|Remote access|Terms and Conditions|Privacy policy|'
    r'\(opens in a new window\)|About content|Accessibility|Contact support|History|Alerts|'
    r'Resource Center|Draw|Return to Home|Zoom structures|Zoom out|Zoom in|Sort descending|Sort ascending|'
    r'Select Reference undefined|View More|Full Text)$')


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


def check_match(match):
    match = (match or 'exact').strip().lower()
    if match not in MATCHES:
        raise ValueError(f'match 只能是 {" / ".join(MATCHES)}（给了「{match}」）')
    return match


def is_cas_rn(s):
    """像不像 CAS 号（只看格式；校验位也算一下，免得把日期之类认成 CAS 号）。"""
    s = (s or '').strip()
    if not CAS_RN_RE.match(s):
        return False
    digits = s.replace('-', '')
    body, check = digits[:-1], int(digits[-1])
    return sum((i + 1) * int(d) for i, d in enumerate(reversed(body))) % 10 == check


def parse_count(s):
    """「Get51Kreferences」「1,194」「Documents - 60,242」→ 整数（K / M 是 SciFinder 的约数）。"""
    m = re.search(r'(\d[\d,.]*)\s*([KM])?', s or '')
    if not m:
        return None
    n = float(m.group(1).replace(',', ''))
    return int(n * {'K': 1000, 'M': 1000000}.get(m.group(2) or '', 1))


def facet_counts(facets):
    """{facet: {值: '13.4K' | '(247)' | None}} → 整数（K / M 是约数）。页面上读不成数的给 None，绝不出 NaN。"""
    return {f: {k: parse_count(v) if v else None for k, v in (bins or {}).items()} for f, bins in (facets or {}).items()}


# 分子式：至少一个元素符号；认高分子的 (C6H6B2O4)x、水合物的 ·xH2O（2026-10-09：均聚物原来被认成「2」）
_FORMULA_RE = re.compile(r'^(?=.*[A-Z])(?:[A-Z][a-z]?\d*(?:\.\d+)?|\(|\)|[·.]|\d|[xn](?=\s*$|\s*[·.)]|[A-Z]))+$')


def norm_sf_substance(x):
    """SciFinder 物质卡片 → {rank, cas_rn, formula, name, preferred_rn, n_references, n_reactions, n_suppliers}。"""
    lines = [ln for ln in (x.get('lines') or []) if _no_ui(ln)]
    rn = x.get('rn') if CAS_RN_RE.match(x.get('rn') or '') else next((ln for ln in lines[:2] if CAS_RN_RE.match(ln)), None)
    formula = next((ln for ln in lines[:4] if _FORMULA_RE.match(ln) and any(c.isdigit() for c in ln)
                    and not CAS_RN_RE.match(ln)), None)
    name = _no_ui(x.get('name')) or next((ln for ln in lines[:5] if ln not in (rn, formula) and not ln.startswith('Preferred')
                                          and not ln.isdigit() and not CAS_RN_RE.match(ln)), None)
    out = {'rank': x.get('rank'), 'type': 'substance', 'cas_rn': rn, 'formula': formula, 'name': name,
           'n_references': parse_count(x.get('refs')), 'n_reactions': parse_count(x.get('rxns')),
           'n_suppliers': parse_count(x.get('sup'))}
    if x.get('preferred'):
        out['preferred_rn'] = x['preferred']
    if any('K' in (x.get(k) or '') or 'M' in (x.get(k) or '') for k in ('refs', 'rxns')):
        out['counts_rounded'] = True        # SciFinder 写 51K 这种约数
    return out


def norm_rx_substance(x):
    """Reaxys 物质条目（整条文字按行）→ {rank, cas_rn, reaxys_rn, name, formula_linear, mw, n_*}。"""
    lines = [ln.strip() for ln in (x.get('lines') or []) if ln.strip()]

    def after(label):
        for i, ln in enumerate(lines[:-1]):
            if ln.rstrip(':') == label.rstrip(':'):
                return lines[i + 1]
        return None
    counts = {}
    for ln in lines:
        m = re.match(r'^(Preparations|Reactions|Documents|Physical Data|Spectra|Bioactivity|Other Data)\s*-\s*([\d,]+)$', ln)
        if m:
            counts[m.group(1)] = int(m.group(2).replace(',', ''))
    mw = after('Molecular Weight:')
    sup = re.search(r'Number of Suppliers:\s*([\d,]+)', ' '.join(lines))
    return {'rank': int(lines[0]) if lines and lines[0].isdigit() else None, 'type': 'substance',
            'cas_rn': (lambda v: v if CAS_RN_RE.match(v or '') else None)(after('CAS Registry Number:')),
            'reaxys_rn': after('Reaxys Registry Number'),
            'name': x.get('name') or None, 'formula_linear': lines[1] if len(lines) > 1 else None,
            'mw': float(mw) if mw and re.match(r'^[\d.]+$', mw) else None,
            'n_documents': counts.get('Documents'), 'n_reactions': counts.get('Reactions'),
            'n_preparations': counts.get('Preparations'), 'n_physical_data': counts.get('Physical Data'),
            'n_spectra': counts.get('Spectra'), 'n_bioactivity': counts.get('Bioactivity'),
            'n_suppliers': int(sup.group(1).replace(',', '')) if sup else None}


def check_sort(sort):
    sort = (sort or '').strip().lower()
    if sort and sort not in SORTS:
        raise ValueError(f'sort 只能是 {" / ".join(SORTS)}（给了「{sort}」）')
    return sort


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


_PATENT_BIB = re.compile(r'^(?P<office>[^,|]+),\s*(?P<no>[A-Z]{2}\d[\dA-Z]*)\s+(?P<kind>[A-Z]\d?)\s+(?P<date>\d{4}-\d{2}-\d{2})')


def parse_sf_bib(bib):
    """SciFinder 每条下面那行出处 → {type, source, year, patent_no, office, date, language}。

    专利：「China, CN117777727 A 2024-03-29 | Language: Chinese, Database: CAplus」
    期刊：「Smart Materials and Structures (2023), 32(7), 074004 | Language: English, Database: CAplus」
    """
    bib = (bib or '').strip()
    head, _, tail = bib.partition('|')
    lang = (re.search(r'Language:\s*([^,|]+)', tail) or [None, None])[1]
    out = {'language': lang.strip() if lang else None}
    m = _PATENT_BIB.match(head.strip())
    if m:
        out.update(type='patent', patent_no=f"{m['no']} {m['kind']}", office=m['office'].strip(),
                   date=m['date'], year=int(m['date'][:4]), source=None)
        return out
    y = re.search(r'\((\d{4})\)', head)
    src = re.split(r'\s*\(\d{4}\)', head)[0].strip() if y else head.strip()
    out.update(type='journal', source=src or None, year=int(y.group(1)) if y else None,
               citation=head.strip() or None)
    return out


# 网页上的按钮字、占位字（2026-10-08 Claude Science 报：名字里出现「Select Substance 3」、CAS 号是「Retrieve CAS RN」、标题「No title」）
_UI_TEXT = re.compile(r'^(Select (Substance|Reference|result).*|Retrieve CAS RN|No title|Image Not Available|'
                      r'View (More|All|Spectra)|Substance in Claims|Full Text|Unspecified)$', re.I)
_BOILER_QI = re.compile(r'^(Try using Advanced Search|Learn more)', re.I)


def _no_ui(s):
    s = (s or '').strip()
    return None if not s or _UI_TEXT.match(s) else s


def clean_qi(s):
    """SciFinder「How we're searching your query」下面那行；经物质跳转时那里只剩一句提示语 → None。"""
    s = (s or '').strip()
    return None if not s or _BOILER_QI.match(s) else s


def _hi(s):
    return re.sub(r'</?(?:hi|mark)>', '', s or '').strip()


MAX_SNIPPET = 400
MAX_AUTHORS = 8
MAX_TERMS = 10


def _slim(item):
    """一页上百条时每条都得精简：摘要片段截到 400 字、作者留前 8 个（n_authors 给总数）。"""
    sn = item.get('snippet')
    if sn and len(sn) > MAX_SNIPPET:
        item['snippet'] = sn[:MAX_SNIPPET].rstrip() + '…'
    au = item.get('authors') or []
    if len(au) > MAX_AUTHORS:
        item['authors'] = au[:MAX_AUTHORS]
        item['n_authors'] = len(au)
    return item


def norm_rx_item(x):
    """Reaxys 页面上抽出来的一条 → 统一字段。序号「4-5」= 同一专利族占了两个号。"""
    idx = (x.get('idx') or '').strip()
    nums = [int(n) for n in re.findall(r'\d+', idx)]
    rank = nums[0] if nums else None
    family = list(range(nums[0], nums[-1] + 1)) if len(nums) == 2 else None
    t = (x.get('type') or '').lower()
    typ = {'article': 'journal', 'review': 'review', 'patent': 'patent'}.get(t, t or None)
    link = x.get('link') or ''
    q = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
    doi = (x.get('doi') or (q.get('doi') or [''])[0] or '').strip().lower() or None
    pub = (q.get('pubno') or [''])[0] or None
    # 年份先信出处里写的（2026-10-08：19 世纪的晶体学文献 online-date 全是 2008 —— 那是 Reaxys 的录入日），
    # 再信 publication-date，最后才是 online-date
    y = re.search(r'\b(1[6-9]\d{2}|20\d{2})\b', x.get('source') or '')
    year = int(y.group(0)) if y else None
    for k in ('pubdate', 'onlinedate'):
        if year or not x.get(k):
            continue
        try:
            year = time.gmtime(int(x[k]) / 1000).tm_year
        except (TypeError, ValueError):
            pass
    if not typ and (pub or x.get('members')):
        typ = 'patent'
    item = {'rank': rank, 'type': typ, 'title': _no_ui(_hi(x.get('title'))), 'authors': x.get('authors') or [],
            'source': None if typ == 'patent' else (x.get('source') or None), 'year': year, 'doi': doi,
            'cited': int(x['cited']) if x.get('cited') else None, 'snippet': x.get('snippet'),
            'index_terms': list(dict.fromkeys(_hi(t) for t in (x.get('index_terms') or []) if _hi(t)))[:MAX_TERMS]}
    if typ == 'patent':
        item.update(patent_no=pub or ((x.get('members') or [None])[0]), family_members=x.get('members') or None,
                    family_ranks=family, office=x.get('office'),
                    assignee=re.sub(r'\s+-\s+[A-Z]{2}\d[\dA-Z]*,\s*\d{4}.*$', '', x.get('assignee') or '') or None)
    return _slim(item)


def norm_sf_item(x):
    b = parse_sf_bib(x.get('bib'))
    authors = [a.strip() for a in (x.get('authors') or '').split(';') if a.strip()]
    item = {'rank': x.get('rank'), 'type': b['type'], 'title': _no_ui(_hi(x.get('title'))), 'authors': authors,
            'source': b.get('source'), 'year': b.get('year'), 'doi': None, 'language': b.get('language'),
            'citing': x.get('citing'), 'substances': x.get('substances'), 'reactions': x.get('reactions'),
            'snippet': (x.get('snippet') or '').strip() or None}
    if b['type'] == 'patent':
        item.update(patent_no=b['patent_no'], office=b['office'], date=b['date'],
                    assignee=x.get('assignee'), status=(x.get('status') or '').lower() or None)
    else:
        item['citation'] = b.get('citation')
    return _slim(item)


def _result(db, **kw):
    r = {'ok': False, 'code': 'OK', 'complete': True, 'warnings': [], 'db': db, 'kind': None, 'query': None,
         'query_interpretation': None, 'page': 0, 'page_size': None, 'pages': None, 'count': None,
         'items': [], 'facets': {}, 'ai_summary': None, 'url': '', 'title': '', 'why': ''}
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


def _find_tab(ctx, db):
    host = SITE[db]['host']
    mine = [p for p in ctx.pages if host in (p.url or '')]
    return mine[-1] if mine else None


def _tab(browser, ctx, db):
    """这个库专用的标签：已有就复用（登录状态、上次的结果都在上面），没有就后台开一个。"""
    pg = _find_tab(ctx, db)
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


def tabs():
    """两个库的标签现在停在哪 —— 只问浏览器，不碰网站（不算一次检索）。"""
    out = {}
    with _session() as (browser, ctx):
        for db in DBS:
            pg = _find_tab(ctx, db)
            url = pg.url if pg else ''
            out[db] = {'tab_open': bool(pg), 'url': url,
                       'login_page': bool(pg) and is_login(db, url),
                       'on_results': bool(page_url(db, url, 1))}
    return out


def _body(pg):
    try:
        return pg.evaluate('document.body ? document.body.innerText : ""') or ''
    except Exception:
        return ''


def _n(pg, sel):
    try:
        return pg.locator(sel).count()
    except Exception:
        return 0


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


def _goto(pg, url):
    try:
        pg.goto(url, wait_until='domcontentloaded', timeout=60000)
        return True
    except Exception as e:
        log.warn(f'打不开 {url}：{str(e)[:120]}')
        return False


_PICK_JS = r"""async ([toggle, pattern]) => {
  // 只点看得见的那个（加了筛选后页面上会多出一个藏着的同名按钮，2026-10-08 实测点到藏着的，菜单不出来）
  const t = [...document.querySelectorAll(toggle)].find(e => e.offsetParent !== null) || document.querySelector(toggle);
  if (!t) return {got: null, seen: [], why: 'no_toggle'};
  const re = new RegExp(pattern, 'i');
  // 已经是要的排序（SciFinder 会记住上一次的排序，2026-10-08 实测按钮上就写着 Times Cited）→ 不用点
  if (re.test((t.innerText || '').trim())) return {got: (t.innerText || '').trim(), seen: [], already: true};
  t.scrollIntoView({block: 'center'}); t.click();
  await new Promise(r => setTimeout(r, 900));
  const opts = [...document.querySelectorAll('[role=menuitem], [role=option], [role=menuitemradio], .dropdown-item, [role=listbox] li')]
    .filter(e => e.offsetParent !== null);
  const seen = opts.map(e => (e.innerText || '').trim()).filter(Boolean);
  const hit = opts.find(e => re.test((e.innerText || '').trim()));
  if (hit) { hit.click(); return {got: (hit.innerText || '').trim(), seen}; }
  t.click();
  return {got: null, seen};
}"""


def _pick(pg, toggle, pattern):
    """点开一个下拉，选文字匹配 pattern 的那项 → (选中的文字 | None, 看到的全部选项)。在页面里点（不怕吸顶栏挡着）。"""
    try:
        r = pg.evaluate(_PICK_JS, [toggle, pattern])
    except Exception as e:
        return None, [f'{type(e).__name__}: {str(e)[:60]}']
    return r.get('got'), r.get('seen') or []


# ── 页面里跑的抽取脚本（改版就改这里）──────────────────────────────────

_SF_JS = r"""async () => {
  // 列表是滚到哪画到哪（2026-10-08 实测：79 条一页，一下子只画出 42 条）—— 滚到底，连续三次数目不变才停
  let last = -1, same = 0;
  for (let i = 0; i < 80 && same < 3; i++) {
    window.scrollTo(0, document.body.scrollHeight); await new Promise(r => setTimeout(r, 500));
    const n = document.querySelectorAll('.reference-data').length;
    same = (n === last) ? same + 1 : 0; last = n;
  }
  window.scrollTo(0, 0);
  const T = e => e ? (e.innerText || '').trim() : '';
  const num = (d, sel) => { const e = d.querySelector(sel); const x = e && (e.getAttribute('aria-label') || '').match(/(\d[\d,]*)/); return x ? +x[1].replace(/,/g, '') : null; };
  const items = [...document.querySelectorAll('.reference-data')].map(d => {
    const a = d.querySelector('.reference-title a');
    let rank = null; try { rank = +new URL(a.href, location.href).searchParams.get('metricsOrdinal') || null; } catch (e) {}
    const txt = d.innerText;
    const m = re => { const x = txt.match(re); return x ? x[1].trim() : null; };
    return {rank, title: T(d.querySelector('.reference-title')), authors: T(d.querySelector('.authors-text')),
      bib: T(d.querySelector('.bibliography')), assignee: m(/Assignee:\s*([^\n]+)/), status: m(/Patent Status:\s*([A-Za-z]+)/),
      snippet: T(d.querySelector('.reference-abstract')), citing: num(d, '.btn-get-citing-references'),
      substances: num(d, '.btn-get-substances'), reactions: num(d, '.btn-get-reactions')};
  });
  const facets = {};
  document.querySelectorAll('.facet-container').forEach(f => {
    const h = T(f.querySelector('.facet-header-title')); const bins = {};
    f.querySelectorAll('.bin-list-item').forEach(li => { const n = T(li.querySelector('.bin-name')); const c = T(li.querySelector('.bin-freq')).replace(/[(),]/g, ''); if (n) bins[n] = c || null; });
    if (h && Object.keys(bins).length) facets[h] = bins;
  });
  const body = document.body.innerText;
  const qi = (body.match(/How we.re searching your query\s*\n+([^\n]+)/) || [])[1] || null;
  let ai = null; const k = body.indexOf('Powered by CAS Newton');
  if (k >= 0) ai = body.slice(k + 21).split(/\n\s*View All\b/)[0].trim();
  return {items, facets, qi, modified: /We.ve modified your query/.test(body), ai,
          checked: [...document.querySelectorAll('input.facet-checkbox:checked')].map(c => c.name + ': ' + c.value)};
}"""

_RX_JS = r"""() => {
  const T = e => e ? (e.innerText || '').trim() : '';
  const items = [...document.querySelectorAll('ul.e2e-results-list > li')].map(li => {
    const b = li.querySelector('[data-e2e="document-title-button"], [data-e2e="patent-family-title"]') || li.querySelector('[data-tracking-citation-type]');
    const g = k => b ? b.getAttribute('data-tracking-' + k) : null;
    const txt = li.innerText;
    const m = re => { const x = txt.match(re); return x ? x[1].trim() : null; };
    const members = [...li.querySelectorAll('.e2e-patent-family-member-item')].map(x => {
      const n = x.innerText.match(/\b([A-Z]{2}\d{5,}[A-Z]?\d*)\s*,\s*(\d{4})\s*,\s*([A-Z]\d?)/); return n ? n[1] + ' ' + n[3] : null; }).filter(Boolean);
    const doiA = li.querySelector('a.doi-link');
    return {idx: T(li.querySelector('.result-checkbox-container__index')), type: g('citation-type'),
      title: g('title') || T(li.querySelector('h3, h4')), authors: [...li.querySelectorAll('.rx-element-authors [data-e2e="author-link"], .rx-element-authors > span')].map(T).filter(Boolean),
      source: T(li.querySelector('.rx-element-literature')), link: g('doc-link'),
      doi: doiA ? T(doiA).replace(/\(opens in a new window\)/, '').trim() : null,
      pubdate: g('publication-date'), onlinedate: g('online-date'), cited: (txt.match(/Cited (\d+) times?/) || [])[1] || null,
      assignee: m(/Current Patent Assignee:\s*([^\n]+)/), office: m(/Office:\s*([^\n]+)/), members,
      snippet: m(/Abstract hit:\s*\{\.\.\.([\s\S]*?)\.\.\.\}/), index_terms: (g('index-terms') || '').split(/;\s*/).filter(Boolean)};
  });
  const body = document.body.innerText;
  let ai = null; const k = body.indexOf('SummaryAI');
  if (k >= 0) ai = body.slice(k + 9).split(/\n\s*View full summary/)[0].split(/\n\s*0\s*\n\s*selected/)[0].trim();
  const list = document.querySelector('ul.e2e-results-list');
  const pg = ((list && list.getAttribute('aria-label')) || '').match(/page (\d+) of (\d+)/);
  const ps = document.querySelector('[role=combobox][aria-label="Results per page"]');
  const f0 = body.indexOf('Search within results'), f1 = body.indexOf('Limit to');
  const facet_names = f0 >= 0 && f1 > f0 ? body.slice(f0, f1).split('\n').map(s => s.trim()).filter(s => s && s !== 'Search within results') : [];
  return {items, ai, page: pg ? +pg[1] : null, pages: pg ? +pg[2] : null, page_size: ps ? +ps.getAttribute('value') : null, facet_names};
}"""

_SF_SUB_JS = r"""() => [...document.querySelectorAll('.substance-tile')].map(t => {
  const T = e => e ? (e.innerText || '').trim() : '';
  const lab = re => { const a = [...t.querySelectorAll('a[aria-label]')].find(a => re.test(a.getAttribute('aria-label'))); return a ? a.getAttribute('aria-label') : null; };
  const txt = t.innerText || '';
  const sel = t.querySelector('input[type=checkbox]');
  const rk = ((sel && (sel.getAttribute('aria-label') || sel.title)) || '').match(/(\d+)\s*$/);
  return {rank: rk ? +rk[1] : null, rn: T(t.querySelector('a.rn-link')), name: T(t.querySelector('.substance-name')),
          lines: txt.split('\n').map(s => s.trim()).filter(Boolean).slice(0, 8),
          refs: lab(/references/i), rxns: lab(/reactions/i), sup: lab(/suppliers/i),
          preferred: (txt.match(/Preferred RN:\s*([\d-]+)/) || [])[1] || null};
})"""

_RX_SUB_JS = r"""() => [...document.querySelectorAll('ul.e2e-results-list > li')].map(li => {
  const n = li.querySelector('.substance-image-container');
  return {name: n ? n.getAttribute('aria-label') : null, lines: (li.innerText || '').split('\n')};
})"""

_SF_MATCH_JS = r"""() => [...document.querySelectorAll('.structure-match-select')].map(b => ({text: (b.innerText || '').trim(), active: /active|selected/.test(b.className)}))"""

_RX_PREVIEW_JS = r"""() => [...document.querySelectorAll('.e2e-view-results')].map((b, i) => {
  let e = b;
  for (let up = 0; up < 8 && e; up++, e = e.parentElement) {
    const t = e.innerText || '';
    const m = t.match(/^\s*(\d[\d,]*)\s*\n\s*(Documents|Substances|Reactions)\b/);
    if (m) {
      const lines = t.split('\n').map(s => s.trim()).filter(Boolean);
      const k = lines.indexOf(m[2]); const end = lines.findIndex(l => l === 'Create Alert');
      return {index: i, count: +m[1].replace(/,/g, ''), kind: m[2].toLowerCase(),
              interpretation: lines.slice(k + 1, end > k ? end : undefined).join(' ')};
    }
  }
  return {index: i, count: null, kind: null, interpretation: null};
})"""


def _ai_pending(s):
    return bool(re.search(r'Generating|may take a few seconds', s or '', re.I))


def _extract(pg, db, raw, max_chars, **kw):
    """读当前列表页 → 结构化结果。库自带的 AI 摘要还在生成，再等一会（最多 25 秒）。"""
    subs = '/search/substance/' in pg.url or '/results/substances/' in pg.url
    if subs:
        return _extract_substances(pg, db, raw, max_chars, **kw)
    js = _SF_JS if db == 'scifinder' else _RX_JS
    d = pg.evaluate(js)
    end = time.time() + 25
    while _ai_pending(d.get('ai')) and time.time() < end:
        pg.wait_for_timeout(2500)
        d = pg.evaluate(js)
    text = clean_text(_body(pg))
    title = ''
    try:
        title = pg.title()
    except Exception:
        pass
    r = _result(db, ok=True, url=pg.url, title=title, count=count_of(db, title, text), **kw)
    r['page'] = page_no(db, pg.url) or 1
    if db == 'scifinder':
        r['items'] = [norm_sf_item(x) for x in d.get('items') or []]
        r['facets'] = facet_counts(d.get('facets'))
        r['query_interpretation'] = clean_qi(d.get('qi'))
        r['query_modified'] = bool(d.get('modified'))
        r['filters_active'] = d.get('checked') or []
    else:
        r['items'] = [norm_rx_item(x) for x in d.get('items') or []]
        r['facets'] = {'available': d.get('facet_names') or []}
        r['pages'] = d.get('pages')
        r['page_size'] = d.get('page_size')
    if r['page_size'] is None and r['items']:
        r['page_size'] = len(r['items'])
    if r['pages'] is None and r['count'] and r['page_size']:
        r['pages'] = -(-r['count'] // r['page_size'])
    r['ai_summary'] = d.get('ai')
    if _ai_pending(d.get('ai')):
        r['warnings'].append('ai_summary_pending')
        r['complete'] = False
    if r['count'] and not r['items']:
        r['warnings'].append('no_items_parsed')
        r['complete'] = False
    if raw:
        r['text'] = text[:max_chars]
        r['truncated'] = len(text) > max_chars
    return r


def _extract_substances(pg, db, raw, max_chars, **kw):
    """物质列表（CAS 号 / 结构式检索落到的那页）→ 结构化。"""
    text = clean_text(_body(pg))
    title = ''
    try:
        title = pg.title()
    except Exception:
        pass
    r = _result(db, ok=True, url=pg.url, title=title, **kw)
    r['page'] = page_no(db, pg.url) or 1
    if db == 'scifinder':
        if _n(pg, '.substance-tile'):
            pg.evaluate('async () => { for (let i = 0; i < 20; i++) { window.scrollTo(0, document.body.scrollHeight); '
                        'await new Promise(r => setTimeout(r, 400)); } window.scrollTo(0, 0); }')
        r['items'] = [norm_sf_substance(x) for x in pg.evaluate(_SF_SUB_JS)]
        base = (r['page'] - 1) * len(r['items'])
        for i, it in enumerate(r['items']):
            if it.get('rank') is None:
                it['rank'] = base + i + 1
        d = pg.evaluate(_SF_JS.replace("'.reference-data'", "'.no-such-thing'"))   # 只借它读 facets / 检索式
        r['facets'] = facet_counts(d.get('facets'))
        r['query_interpretation'] = clean_qi(d.get('qi'))
        r['filters_active'] = d.get('checked') or []
        m = re.search(r'(?m)^([\d,]+)\s+Results?$', text)
        r['count'] = int(m.group(1).replace(',', '')) if m else None
        r['structure_match'] = pg.evaluate(_SF_MATCH_JS) or None
    else:
        r['items'] = [norm_rx_substance(x) for x in pg.evaluate(_RX_SUB_JS)]
        r['count'] = count_of(db, title, text)
        d = pg.evaluate(_RX_JS)
        r['pages'], r['page_size'] = d.get('pages'), d.get('page_size')
    if r['page_size'] is None and r['items']:
        r['page_size'] = len(r['items'])
    if r['pages'] is None and r['count'] and r['page_size']:
        r['pages'] = -(-r['count'] // r['page_size'])
    if r['count'] and not r['items']:
        r['warnings'].append('no_items_parsed')
        r['complete'] = False
    if raw:
        r['text'] = text[:max_chars]
        r['truncated'] = len(text) > max_chars
    return r


def _sf_within(pg, terms, warnings):
    """左侧「Search Within Results」：最多 3 个词，和当前结果取交集（CAS 号 + 主题词就靠它）。"""
    terms = [t for t in (terms if isinstance(terms, list) else [terms]) if t][:3]
    if not terms:
        return []
    # 这一栏默认是收着的（aria-expanded=false）：输入框在 DOM 里、字也填得进，但「Search」点不着 ——
    # 2026-10-08 实测填了词结果数没变。先展开再填再点。
    head = pg.locator('.text-search-within-results-facet button.facet-header')
    if head.count() and head.first.get_attribute('aria-expanded') == 'false':
        head.first.click()
        pg.wait_for_timeout(800)
    box = pg.locator('.text-search-within-results-facet input.text-query-input')
    n = box.count()
    if not n:
        warnings.append('within_box_missing: 找不到「Search Within Results」的输入框')
        return []
    for i, t in enumerate(terms[:n]):
        box.nth(i).fill(t)
    if len(terms) > n:
        warnings.append(f'within_truncated: 页面只有 {n} 个框，多出来的词没用上')
    before = _body(pg)
    m0 = re.search(r'(?m)^([\d,]+)\s+Results?$', before)
    pg.locator('.text-search-within-results-facet .search-button').first.click()
    pg.wait_for_timeout(3000)
    _wait_items(pg, 'scifinder')
    m1 = re.search(r'(?m)^([\d,]+)\s+Results?$', _body(pg))
    if m0 and m1 and m0.group(1) == m1.group(1):
        warnings.append(f'within_no_effect: 结果数没变（{m1.group(1)}），这个词可能没生效')
    return terms[:n]


def _sf_filters(pg, filters, warnings):
    """SciFinder 左侧筛选：{facet 名: [值, …]}（名字与 facets 里看到的一致），另认 yearFrom / yearTo。"""
    applied = []
    filters = dict(filters or {})
    y0, y1 = filters.pop('yearFrom', None), filters.pop('yearTo', None)
    for facet, vals in filters.items():
        for v in (vals if isinstance(vals, list) else [vals]):
            box = pg.locator(f'input.facet-checkbox[name="{facet}"][value="{v}"]')
            if box.count() == 0:
                warnings.append(f'filter_not_found: {facet}={v}（只有当前页面左侧显示的值能选）')
                continue
            bid = box.first.get_attribute('id')
            # 这一栏可能是收着的（2026-10-08 实测 Concept 收着时选项点不着）→ 先展开
            head = box.first.locator('xpath=ancestor::*[contains(@class,"facet-container")][1]').locator('button.facet-header')
            if head.count() and head.first.get_attribute('aria-expanded') == 'false':
                head.first.click()
                pg.wait_for_timeout(800)
            pg.locator(f'label[for="{bid}"]').first.click()
            _settle(pg, lambda t: True, timeout=20)
            applied.append(f'{facet}: {v}')
    if y0 or y1:
        try:
            pg.fill('#start-date', f'{int(y0)}-01-01' if y0 else '')
            pg.fill('#end-date', f'{int(y1)}-12-31' if y1 else '')
            btn = pg.locator('.publication-date button:has-text("Apply"), button:has-text("Apply")')
            btn.first.click()
            _settle(pg, lambda t: True, timeout=25)
            applied.append(f'Publication Date: {y0 or ""}–{y1 or ""}')
        except Exception as e:
            warnings.append(f'year_filter_failed: {str(e)[:80]}')
    return applied


def _wait_items(pg, db, timeout=45):
    sel = SITE[db]['item']
    end, prev = time.time() + timeout, -1
    while time.time() < end:
        n = _n(pg, sel)
        if n and n == prev:
            return True
        if 'No results' in _body(pg)[:4000]:
            return True
        prev = n
        pg.wait_for_timeout(1500)
    return False


def _sf_home(pg):
    """回首页、等搜索框；顺手拿掉上一次留在搜索栏里的结构（不拿掉会和这次的检索叠在一起搜）。"""
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
    for _ in range(3):
        rm = pg.locator('a.remove-structure-query')
        if not rm.count():
            break
        rm.first.click()
        pg.wait_for_timeout(800)
    pg.fill(s['input'], '')
    return None


def _sf_draw(pg, structure, kind, warnings):
    """结构式进 CAS Draw（「Add to editor」收 SMILES / 名字），选检索什么（物质 / 文献 / 反应），确定。→ 认出的分子式或 None。"""
    s = SITE['scifinder']
    pg.click('#draw-btn')
    pg.wait_for_selector('#cdAddToEditorTextBox', timeout=30000)
    pg.wait_for_timeout(1500)
    try:
        pg.click('#cdFileNew')                 # 清掉画板上上一次的结构
        pg.wait_for_timeout(500)
    except Exception:
        pass
    pg.fill('#cdAddToEditorTextBox', structure)
    pg.click('#cdAddToEditorButton')
    pg.wait_for_timeout(2500)
    mf = pg.evaluate("() => ((document.querySelector('.editor-modal-container') || document.body).innerText"
                     ".match(/Molecular Formula:\\s*([^\\n]*)/) || [])[1] || ''").strip()
    if not mf:
        warnings.append('structure_not_recognized: CAS Draw 没认出这个结构式（看看 SMILES 写对没有）')
    pg.click(s['draw_type'][kind])
    pg.wait_for_timeout(500)
    pg.locator('.editor-modal-container button:has-text("OK")').first.click()
    pg.wait_for_timeout(1500)
    return mf or None


def _sf_match(pg, match, warnings):
    """结构检索结果页上的 As Drawn / Substructure / Similarity 三个按钮，点要的那个。"""
    label = SITE['scifinder']['match_label'][match]
    btns = pg.locator(SITE['scifinder']['match_btn'])
    for i in range(btns.count()):
        t = (btns.nth(i).inner_text() or '').strip()
        if t.startswith(label):
            btns.nth(i).click()
            pg.wait_for_timeout(2500)
            _wait_items(pg, 'scifinder')
            return t
    warnings.append(f'match_not_found: {label}（结果页没有这个按钮）')
    return None


def _sf_to_refs_of_first_substance(pg, warnings):
    """物质列表 → 第一个物质的「Get … references」→ 用了它的文献 / 专利。"""
    a = pg.locator('.substance-tile a.btn-get-references, .substance-tile a[aria-label*="references" i]')
    if not a.count():
        warnings.append('no_references_link: 这个物质没有「Get references」')
        return False
    label = a.first.get_attribute('aria-label') or ''
    a.first.click()
    try:
        pg.wait_for_url(re.compile(r'/search/reference/'), timeout=45000)
    except Exception:
        warnings.append('references_page_timeout')
        return False
    warnings.append(f'via_substance: 先落到物质，再取它的文献（{label}）')
    return True


def _search_scifinder(pg, query, kind, sort, filters, mode, raw, max_chars, structure='', match='exact', subset=None,
                      within=None):
    s = SITE['scifinder']
    err = _sf_home(pg)
    if err:
        return err
    warnings, extra = [], {}
    if structure:
        extra['structure_formula'] = _sf_draw(pg, structure, kind, warnings)
        if query:
            pg.fill(s['input'], query)
    else:
        pg.fill(s['input'], query)
    pg.click(s['submit'])
    try:
        pg.wait_for_url(re.compile(r'/search/'), timeout=60000)
    except Exception:
        return _result('scifinder', code='TIMEOUT', url=pg.url, why='提交后没跳到结果页', warnings=warnings)
    want_seg = {'references': '/search/reference/', 'substances': '/search/substance/', 'reactions': '/search/reaction/'}[kind]
    if '/search/all/' in pg.url:
        # 总览页是分块加载的（2026-10-08 实测：物质、反应先到，文献那块晚好几秒）——
        # 专门等要的那个「View All …」；等满了还没有才算这一类没结果
        want = s['view_all'][kind]
        _settle(pg, lambda t: want in t or 'No results' in t, timeout=45)
        link = pg.locator(f'text={want}')
        if link.count() == 0:
            r = _result('scifinder', ok=True, code='NO_RESULTS', count=0, url=pg.url, warnings=warnings,
                        why=f'这次搜索没有 {kind} 结果', **extra)
            if raw:
                r['text'] = clean_text(_body(pg))[:max_chars]
            return r
        link.first.click()
        try:
            pg.wait_for_url(re.compile(s['page_re']), timeout=45000)
        except Exception:
            return _result('scifinder', code='TIMEOUT', url=pg.url, why=f'点了 {want} 没跳到列表页', warnings=warnings)
    ok = _wait_items(pg, 'scifinder')
    if structure:
        extra['structure_match'] = _sf_match(pg, match, warnings)
        ok = _wait_items(pg, 'scifinder')
    if kind == 'references' and '/search/substance/' in pg.url:
        # CAS 号（或结构式按物质落地）要文献：从物质跳到「用了它的文献」
        if not _sf_to_refs_of_first_substance(pg, warnings):
            r = _extract(pg, 'scifinder', raw, max_chars, **extra)
            r['warnings'] = warnings + r['warnings']
            return r
        ok = _wait_items(pg, 'scifinder')
        # 经物质跳过来的文献页上没有「How we're searching」那一行 —— 自己写一句
        extra['query_interpretation_note'] = f'references of substance {query or structure} (via its "Get references")'
    elif want_seg not in pg.url:
        warnings.append(f'landed_on_other_list: 要 {kind}，落在 {pg.url.split("/search/")[-1][:20]}')
    if mode == 'original':
        b = pg.locator(s['original'])
        if b.count():
            b.first.click()
            pg.wait_for_timeout(2000)
            ok = _wait_items(pg, 'scifinder')
        else:
            warnings.append('original_mode_unavailable: 这次 SciFinder 没改写检索式')
    if within:
        extra['within_applied'] = _sf_within(pg, within, warnings)
    applied = _sf_filters(pg, filters, warnings) if filters else []
    if sort:
        got, seen = _pick(pg, s['sort'], SORTS[sort])
        if got:
            _wait_items(pg, 'scifinder')
        else:
            warnings.append(f'sort_not_found: {sort}（看到的选项：{", ".join(seen) or "无"}）')
    note = extra.pop('query_interpretation_note', None)
    r = _extract(pg, 'scifinder', raw, max_chars, filters_applied=applied, sort=sort or 'relevance', mode=mode, **extra)
    r['warnings'] = warnings + r['warnings']
    if note and not r.get('query_interpretation'):
        r['query_interpretation'] = note + (f'; within: {", ".join(extra["within_applied"])}' if extra.get('within_applied') else '')
    if not ok:
        r.update(code='TIMEOUT', complete=False, why='列表页还在加载，读到的可能不全')
    return r


def _rx_page_size_max(pg):
    """Reaxys 每页条数调到最大（默认 15）。网站会记住，之后翻页也是这个数。→ 现在的每页条数。"""
    box = pg.locator(SITE['reaxys']['page_size'])
    if box.count() == 0:
        return None
    cur = box.first.get_attribute('value')
    box.first.click()
    pg.wait_for_timeout(800)
    opts = pg.locator('[role=option]')
    nums = []
    for i in range(min(opts.count(), 12)):
        t = (opts.nth(i).inner_text() or '').strip()
        if t.isdigit():
            nums.append((int(t), i))
    if not nums or str(max(nums)[0]) == cur:
        pg.keyboard.press('Escape')
        return int(cur) if cur and cur.isdigit() else None
    best, i = max(nums)
    opts.nth(i).click()
    pg.wait_for_timeout(1500)
    _wait_items(pg, 'reaxys')
    return best


_RX_IMPORT_JS = r"""async ([mol, fmt]) => {
  const f = document.querySelector('iframe[src*="structure-editor"]');
  if (!f || !f.contentWindow.marvin || !f.contentWindow.marvin.sketcherInstance) return {ok: false, why: 'no_editor'};
  const sk = f.contentWindow.marvin.sketcherInstance;
  try { sk.clear && sk.clear(); } catch (e) {}
  try { await sk.importStructure(fmt, mol); } catch (e) { return {ok: false, why: String(e).slice(0, 120)}; }
  let back = ''; try { back = await sk.exportStructure('smiles'); } catch (e) {}
  return {ok: !!back, smiles: back};
}"""


def _rx_draw(pg, structure, match, warnings):
    """结构式进 Reaxys 的 MarvinJS（importStructure）→ 选检索方式 → Transfer to query → Search。→ 编辑器里读回的 SMILES。"""
    pg.locator(SITE['reaxys']['draw']).first.click()
    pg.wait_for_selector('iframe[src*="structure-editor"]', timeout=30000)
    got = None
    for _ in range(20):                       # 编辑器要加载一会
        pg.wait_for_timeout(1000)
        got = pg.evaluate(_RX_IMPORT_JS, [structure, 'mol' if 'M  END' in structure else 'smiles'])
        if got.get('why') != 'no_editor':
            break
    if not got or not got.get('ok'):
        warnings.append(f'structure_not_recognized: MarvinJS 没收下这个结构式（{(got or {}).get("why", "")}）')
        return None
    # 在页面里按文字点单选（Playwright 的 text-is 对这几个 label 不灵，2026-10-08 实测「Similar」找不到）
    hit = pg.evaluate("""(t) => { const l = [...document.querySelectorAll('label')].find(x => (x.innerText || '').trim() === t);
        if (!l) return false; l.click(); return true; }""", SITE['reaxys']['match_label'][match])
    if not hit:
        warnings.append(f'match_not_found: {SITE["reaxys"]["match_label"][match]}（编辑器页面上没有这个选项）')
    pg.wait_for_timeout(600)
    # 按 data-e2e 在页面里点（选了 Similar 之后 text-is 找不到它，2026-10-08 实测；按钮其实在）
    if not pg.evaluate("""() => { const b = document.querySelector('[data-e2e="structure-editor-transfer"]');
        if (!b) return false; b.click(); return true; }"""):
        warnings.append('transfer_button_missing: 编辑器页面上找不到 Transfer to query')
        return None
    pg.wait_for_url(re.compile(r'#/search/quick/query'), timeout=30000)
    pg.wait_for_timeout(1500)
    return got.get('smiles')


def _rx_to_docs_of_first_substance(pg, warnings, extra=None):
    """Reaxys 物质列表 → 文献最多的那个物质的「Documents - N」→ 它的文献。

    一个 CAS 号在 Reaxys 里可以对应好几个物质（2026-10-08：硼酸 10043-35-3 对应 7 个，第一个是只有 9 篇
    19 世纪晶体学文献的条目）—— 挑文献最多的，候选全列进 substance_candidates。
    """
    cands = [norm_rx_substance(x) for x in pg.evaluate(_RX_SUB_JS)]
    best = max(range(len(cands)), key=lambda i: cands[i].get('n_documents') or 0) if cands else 0
    if extra is not None and cands:
        extra['substance_candidates'] = [{k: c.get(k) for k in ('rank', 'cas_rn', 'reaxys_rn', 'name', 'formula_linear',
                                                                'n_documents')} for c in cands[:20]]
        extra['substance_chosen'] = cands[best].get('reaxys_rn')
    b = pg.locator('ul.e2e-results-list > li').nth(best).locator('button:has-text("Documents -"), a:has-text("Documents -")')
    if not b.count():
        warnings.append('no_documents_link: 这个物质没有「Documents」')
        return False
    label = (b.first.inner_text() or '').strip()
    b.first.click()
    try:
        pg.wait_for_url(re.compile(r'/results/citations/'), timeout=60000)
    except Exception:
        warnings.append('documents_page_timeout')
        return False
    warnings.append(f'via_substance: 先落到物质，再取它的文献（{label}）')
    return True


RX_CAS_MIN_DOCS = 50     # CAS 号落到的 Reaxys 物质文献都少于这个数 → 多半是冷门条目，改按结构搜（见 cas_smiles）


def _search_reaxys(pg, query, kind, sort, filters, mode, raw, max_chars, structure='', match='exact', subset=None,
                   cas_smiles='', force_via=False):
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
    warnings, extra = [], {}
    for _ in range(3):                        # 上一次的结构还挂在搜索框上，不拿掉会叠在一起搜（2026-10-08 实测叠过）
        rm = pg.locator(s['clear_structure'])
        if not rm.count():
            break
        rm.first.click()
        pg.wait_for_timeout(800)
    pg.fill(s['input'], '')
    rx_cas = is_cas_rn(query) and not structure
    if structure:
        extra['structure_smiles'] = _rx_draw(pg, structure, match, warnings)
        if extra['structure_smiles'] is None:
            return _result('reaxys', code='NO_RESULTS', url=pg.url, warnings=warnings, why='结构式没收下')
        extra['structure_match'] = match
        if query:
            pg.fill(s['input'], query)
        pg.locator(s['search']).first.click()
    else:
        pg.fill(s['input'], query)
        pg.keyboard.press('Enter')
    # 预览页：Reaxys 把一句话拆成几组子查询，各给一个数和一个 View Results（从严到宽排）
    if not _settle(pg, lambda t: 'View Results' in t or 'No results' in t, timeout=60):
        return _result('reaxys', code='TIMEOUT', url=pg.url, why='等不到结果预览', warnings=warnings)
    preview = pg.evaluate(_RX_PREVIEW_JS)
    # CAS 号要文献：文献那组是「标题里出现这串数字」的字面匹配，不对 —— 先落到物质，再取它的文献
    via = kind == 'references' and (rx_cas or force_via)
    word = 'substances' if via else s['card_word'][kind]
    if subset is not None:
        # 调用方自己挑预览里的哪一组（相似检索分 tight / near / average / wide / widest 五档；关键词拆成几组子检索）
        pick = preview[int(subset)] if 0 <= int(subset) < len(preview) and preview[int(subset)].get('kind') else None
        if pick and not via:
            word = pick['kind']
    else:
        pick = next((c for c in preview if c.get('kind') == word), None)
    if not pick:
        return _result('reaxys', ok=True, code='NO_RESULTS', count=0, url=pg.url, preview=preview, warnings=warnings,
                       why=f'预览里没有 {word} 这一组（preview 里是 Reaxys 拆出来的各组）', **extra)
    pg.locator(s['view_results']).nth(pick['index']).click()
    try:
        pg.wait_for_url(re.compile(s['page_re']), timeout=60000)
    except Exception:
        return _result('reaxys', code='TIMEOUT', url=pg.url, preview=preview, why='点了 View Results 没跳到列表页',
                       warnings=warnings)
    ok = _wait_items(pg, 'reaxys', timeout=60)
    if via and rx_cas and cas_smiles:
        cands = [norm_rx_substance(x) for x in pg.evaluate(_RX_SUB_JS)]
        top = max([c.get('n_documents') or 0 for c in cands] or [0])
        if top < RX_CAS_MIN_DOCS:
            # Reaxys 的 CAS 号登记不全（硼酸 10043-35-3 只挂在 7 个矿物 / 水合物条目上，最多 9 篇）→ 按结构搜主条目
            r = _search_reaxys(pg, '', kind, sort, filters, mode, raw, max_chars, structure=cas_smiles, match='exact',
                               force_via=True)
            r['warnings'] = warnings + [f'cas_fallback_to_structure: Reaxys 里 {query} 只挂在文献很少的条目上'
                                        f'（最多 {top} 篇），改按结构 {cas_smiles} 搜'] + r.get('warnings', [])
            r['cas_candidates_reaxys'] = [{k: c.get(k) for k in ('reaxys_rn', 'name', 'formula_linear', 'n_documents')}
                                          for c in cands[:10]]
            return r
    if via:
        if not _rx_to_docs_of_first_substance(pg, warnings, extra):
            r = _extract(pg, 'reaxys', raw, max_chars, preview=preview, **extra)
            r['warnings'] = warnings + r['warnings']
            return r
        ok = _wait_items(pg, 'reaxys', timeout=60)
    try:
        _rx_page_size_max(pg)
    except Exception as e:
        warnings.append(f'page_size_failed: {str(e)[:80]}')
    if mode == 'original':
        warnings.append('original_mode_n/a: Reaxys 不改写检索式，它把整句拆成子检索（见 preview），自己挑哪组')
    if filters:
        warnings.append('filters_not_supported_for_reaxys_yet: 只有 SciFinder 支持 filters；Reaxys 的筛选项名在 facets.available')
    if sort:
        got, seen = _pick(pg, s['sort'], SORTS[sort])
        if got:
            _wait_items(pg, 'reaxys')
        else:
            warnings.append(f'sort_not_found: {sort}（看到的选项：{", ".join(seen) or "无"}）')
    r = _extract(pg, 'reaxys', raw, max_chars, preview=preview, sort=sort or 'relevance', mode=mode,
                 query_interpretation=pick.get('interpretation'), **extra)
    r['warnings'] = warnings + r['warnings']
    if not ok:
        r.update(code='TIMEOUT', complete=False, why='列表页还在加载，读到的可能不全')
    return r


# ══════════════════════════════════════════════════════════════════════
# 对外
# ══════════════════════════════════════════════════════════════════════

def search(db, query='', kind='references', structure='', match='exact', sort=None, filters=None, mode='auto',
           raw=False, max_chars=30000, subset=None, within=None, cas_smiles=''):
    """在 SciFinder / Reaxys 里搜一次，读结果列表第 1 页。

    query：关键词或 CAS 号；structure：SMILES（Reaxys 也收 molfile），match = exact / substructure / similarity。
    CAS 号 + kind=references：先落到这个物质，再取用了它的文献 / 专利。
    sort: relevance / date / cited；filters（只 SciFinder）：{facet 名: [值]} + yearFrom / yearTo；
    mode='original'：SciFinder 改写了检索式时点「Search Original Query」按原样搜。
    """
    db, kind, sort, match = check_db(db), check_kind(kind), check_sort(sort), check_match(match)
    query, structure = (query or '').strip(), (structure or '').strip()
    if not query and not structure:
        raise ValueError('query 和 structure 至少给一个')
    mode = (mode or 'auto').lower()
    log.info(f'{db} 搜索（{kind}，structure={structure or "-"}/{match}，sort={sort or "-"}，filters={filters or "-"}）：{query}')
    with _session() as (browser, ctx):
        pg = _tab(browser, ctx, db)
        try:
            if db == 'scifinder':
                r = _search_scifinder(pg, query, kind, sort, filters, mode, raw, max_chars, structure=structure,
                                      match=match, subset=subset, within=within)
            else:
                r = _search_reaxys(pg, query, kind, sort, filters, mode, raw, max_chars, structure=structure,
                                   match=match, subset=subset, cas_smiles=cas_smiles or '')
            if within and db != 'scifinder':
                r.setdefault('warnings', []).append('within_not_supported_for_reaxys: 把主题词并进 query 让 Reaxys 拆子检索，或用 SciFinder')
        except Exception as e:
            log.warn(f'{db} 搜索出错：{type(e).__name__}: {str(e)[:200]}')
            r = _result(db, code='TIMEOUT', complete=False, url=getattr(pg, 'url', ''),
                        why=f'{type(e).__name__}: {str(e)[:200]}')
    r.update(kind=kind, query=query or None)
    if structure:
        r.update(structure=structure, match=match)
    return r


def page(db, n, base_url='', raw=False, max_chars=30000):
    """结果列表第 n 页。base_url = 那次 search 回的 url（缓存命中后标签可能停在别处，所以要带）。"""
    db = check_db(db)
    n = int(n)
    if n < 1:
        raise ValueError('页码从 1 开始')
    with _session() as (browser, ctx):
        pg = _tab(browser, ctx, db)
        url = page_url(db, base_url or pg.url, n)
        if not url:
            if is_login(db, pg.url):
                return _result(db, code='LOGIN_REQUIRED', url=pg.url, why='要登录：请人在主力机浏览器里登录')
            return _result(db, code='NO_SEARCH', url=pg.url, why='没有结果列表可翻，先 search')
        if not _goto(pg, url):
            return _result(db, code='NAVIGATE_FAILED', url=url, why='翻页打不开')
        if db == 'reaxys':
            # Reaxys 是 # 路由，goto 同一文档只换 hash 时不一定重画，补一次刷新
            pg.reload(wait_until='domcontentloaded')
        if is_login(db, pg.url):
            return _result(db, code='LOGIN_REQUIRED', url=pg.url, why='要登录：请人在主力机浏览器里登录')
        ok = _wait_items(pg, db)
        r = _extract(pg, db, raw, max_chars)
        if not ok:
            r.update(code='TIMEOUT', complete=False, why='列表页还在加载，读到的可能不全')
        return r
