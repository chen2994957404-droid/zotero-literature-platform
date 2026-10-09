# -*- coding: utf-8 -*-
"""polyinfo · NIMS 聚合物数据库 PoLyInfo —— 借人已经登录好的浏览器，按人的节奏查、读页面

**为什么有这块（2026-10-09 用户定）**：PoLyInfo 有大量聚合物实测性质（Tg、密度、模量、竞聚率相关的
组成–性质表），Claude Science 进不去（要 DICE 账号 + MatNavi 使用批准）；人查完再截图给它太费事。
用户原话：「不是要批量抓取数据，只是省去我截图的过程，需要我点的时候我点一下」。

查证过的现实（2026-10-09）：
  - **没有公开的程序接口**，MDR 上的 PoLyInfo 论文也不附数据。2017 年 NIMS 文件提过 MatNavi 付费接口，文档只在所内。
  - 条款：禁止批量下载、禁止网页抓取（人工或机器都算），有嫌疑就停账号。
  - 网站自带人机验证：样品详情页（sample-information）每次都要输图片里的字符；查得频繁时检索也会弹。
所以这块的形状和 chemdb 一样：**不自己发请求，接管主力机「取全文用的浏览器」里 PoLyInfo 的标签**，
一次只看一页，**碰到验证码立刻停、回 CAPTCHA_REQUIRED，由人去点**。这里没有、也不许有任何填验证码的代码。

⚠ 只读：检索、看样品列表、看一个样品的详情。不翻全库、不导出、不登录（登录永远是人做）。
⚠ 频率（每次间隔、每天上限、缓存）由调用方管（host/mcp/science.py），这块只管「怎么在页面上查」。

页面三层（2026-10-09 实测）：
  1. 检索页 /PoLyInfo/search → 结果列表 /PoLyInfo/polymer-list：每种聚合物一条，所选性质的中位数 / 众数 / 点数
  2. 点「N samples」→ /PoLyInfo/sample-list：每个样品一行，列出它的各项性质值
  3. 点样品编号 → /PoLyInfo/sample-information：组成、聚合条件、分子量、出处（DOI）、原文的「组成–性质」表（**要人机验证**）

对外接口：
  | 函数 | 说明 |
  |---|---|
  | `search(name='', pid='', formula=None, prop='', atoms_only=False)` | 检索 → 结果列表第 1 页 |
  | `samples(pid)` | 一种聚合物（PID / COID / BDID）的样品列表 |
  | `sample(pid, n=1)` | 第 n 个样品的详情；撞验证码回 CAPTCHA_REQUIRED，页面停在那儿等人 |
  | `current()` | 不导航：读 PoLyInfo 标签上现在那一页（人点完验证码后用；不算一次访问） |
  | `status()` | 标签在不在、要不要登录、有没有验证码挡着 —— 只看浏览器，不碰网站 |
  | `parse_list` / `parse_samples` / `parse_sample_info` / `page_kind` / `is_captcha` / `is_login` / `formula_counts` | 纯函数（自测覆盖） |

返回 dict：ok, code, page_kind, url, why, warnings，加上该页的字段（items / samples / sample）。
code：OK / NO_RESULTS / LOGIN_REQUIRED / CAPTCHA_REQUIRED / NOT_FOUND / NAVIGATE_FAILED / TIMEOUT。
只有「浏览器连不上 / 没装 playwright」才抛异常（沿用 pdf_fetch 的两个异常）。
"""
import contextlib
import re
import time

from shared.adapters import pdf_fetch
from shared.kernel.log import get_logger

log = get_logger('polyinfo')

HOST = 'polymer.nims.go.jp'
SEARCH_URL = 'https://polymer.nims.go.jp/PoLyInfo/search'
CAPTCHA_TEXT = 'Type the characters see in the picture'
LOGIN_RE = re.compile(r'b2clogin\.com|dicelogin|/login\b|diceidm\.nims\.go\.jp/auth')
ID_RE = re.compile(r'^(P\d{6}|BD\d{6}|CU\d{6})$')
ELEMENTS = ('C', 'H', 'B', 'Br', 'Cl', 'D', 'F', 'Fe', 'Si', 'Ge', 'I', 'N', 'Na', 'O', 'P', 'S', 'Sn')
MAX_ELEMENTS = 6                  # 检索页上「CU Formula」一共 6 格


# ══════════════════════════════════════════════════════════════════════
# 纯函数（自测覆盖）
# ══════════════════════════════════════════════════════════════════════

def is_captcha(text):
    return CAPTCHA_TEXT.lower() in (text or '').lower()


def is_login(url):
    return bool(LOGIN_RE.search(url or ''))


def page_kind(url):
    """search / polymer_list / sample_list / sample_info / login / other。"""
    u = url or ''
    if is_login(u):
        return 'login'
    for k, pat in (('polymer_list', '/polymer-list'), ('sample_list', '/sample-list'),
                   ('sample_info', '/sample-information'), ('search', '/PoLyInfo/search')):
        if pat in u:
            return k
    return 'other'


def check_id(pid):
    pid = (pid or '').strip().upper()
    if not ID_RE.match(pid):
        raise ValueError(f'PoLyInfo 编号形如 P040048（均聚物）/ P905362（共聚物 COID）/ BD000088（共混）/ CU040048，给了「{pid}」')
    return pid


def formula_counts(formula):
    """'C16H38O5Si4' 或 {'C':16,...} → [('C','16'), ...]（检索页的元素格只认这 17 种元素、最多 6 格）。"""
    if not formula:
        return []
    if isinstance(formula, dict):
        pairs = [(k, str(v)) for k, v in formula.items()]
    else:
        pairs = re.findall(r'([A-Z][a-z]?)(\d*)', str(formula).replace(' ', ''))
        pairs = [(e, n or '1') for e, n in pairs]
    bad = [e for e, _ in pairs if e not in ELEMENTS]
    if bad:
        raise ValueError(f'PoLyInfo 的分子式检索只认这些元素：{" ".join(ELEMENTS)}（不认 {" ".join(bad)}）')
    if len(pairs) > MAX_ELEMENTS:
        raise ValueError(f'分子式检索最多 {MAX_ELEMENTS} 种元素（给了 {len(pairs)} 种）')
    return pairs


def _num(s):
    s = (s or '').strip()
    try:
        return float(s)
    except ValueError:
        return None


_ITEM_HEAD = re.compile(r'^(\d+)\.\s+(.+)$')
_ITEM_ID = re.compile(r'^(PID|COID|BDID):\s*(\S+)\s+CU formula:\s*(\S+)\s+(\d+)\s*samples', re.I)
_PROP_ROW = re.compile(r'^(?P<name>.+?)\s*\[(?P<unit>[^\]]*)\]\t(?P<median>[^\t]*)\t(?P<mode>[^\t]*)\t(?P<var>[^\t]*)\t*\((?P<n>\d+)\s*points?\)')
_MATCHES = re.compile(r'Matches:\s*([\d,]+)\s*polymers? (?:were|was) found', re.I)
_TYPES = re.compile(r'Homopolymer:\s*(\d+)\s+Copolymer:\s*(\d+)\s+Polymer Blend:\s*(\d+)', re.I)


def parse_list(text):
    """结果列表页的文字 → {count, n_homopolymer, n_copolymer, n_blend, items[]}。
    每条：rank, name, id_type（PID / COID / BDID）, id, cu_formula, n_samples, properties[{name, unit, median, mode, variance, points}]。"""
    out = {'count': None, 'n_homopolymer': None, 'n_copolymer': None, 'n_blend': None, 'items': []}
    m = _MATCHES.search(text or '')
    if m:
        out['count'] = int(m.group(1).replace(',', ''))
    m = _TYPES.search(text or '')
    if m:
        out['n_homopolymer'], out['n_copolymer'], out['n_blend'] = (int(x) for x in m.groups())
    cur = None
    for raw in (text or '').splitlines():
        ln = raw.strip('\r')
        s = ln.strip()
        h = _ITEM_HEAD.match(s)
        if h and not _PROP_ROW.match(ln.strip()):
            cur = {'rank': int(h.group(1)), 'name': h.group(2).strip(), 'id_type': None, 'id': None,
                   'cu_formula': None, 'n_samples': None, 'properties': []}
            out['items'].append(cur)
            continue
        if cur is None:
            continue
        i = _ITEM_ID.match(s)
        if i:
            cur.update(id_type=i.group(1).upper(), id=i.group(2), cu_formula=i.group(3), n_samples=int(i.group(4)))
            continue
        p = _PROP_ROW.match(s)
        if p:
            cur['properties'].append({'name': p['name'].strip(), 'unit': p['unit'], 'median': _num(p['median']),
                                      'mode': p['mode'].strip() or None, 'variance': _num(p['var']),
                                      'points': int(p['n'])})
    return out


_SAMPLE_ROW = re.compile(r'^(\d+)\t(\d{7}-\d{3}-\d{3}-\d{3})\t([^\t]*)\t([^\t]*)\t([^\t]*)')
_SAMPLE_PROP = re.compile(r'^(?P<name>.+?)\s+(?P<value>[-+]?[\d.]+(?:e[-+]?\d+)?)\s*\[(?P<unit>[^\]]*)\]$', re.I)


def parse_samples(text):
    """样品列表页 → {n_points, samples[{no, sample_id, material_type, additives, polymer_type, properties[{name, value, unit}]}]}。"""
    out = {'n_points': None, 'samples': []}
    m = re.search(r'Number of data points:\s*(\d+)', text or '')
    if m:
        out['n_points'] = int(m.group(1))
    cur = None
    for raw in (text or '').splitlines():
        s = raw.strip()
        r = _SAMPLE_ROW.match(s)
        if r:
            cur = {'no': int(r.group(1)), 'sample_id': r.group(2), 'material_type': r.group(3).strip() or None,
                   'additives': (r.group(4).strip() if r.group(4).strip() not in ('', '-') else None),
                   'polymer_type': r.group(5).strip() or None, 'properties': []}
            out['samples'].append(cur)
            continue
        if cur is None:
            continue
        p = _SAMPLE_PROP.match(s)
        if p:
            cur['properties'].append({'name': p['name'].strip(), 'value': _num(p['value']), 'unit': p['unit']})
        elif s.startswith('«'):
            cur = None
    return out


_INFO_KEYS = ('Sample ID', 'Polymer ID', 'Name', 'Polymer type', 'Copolymer Type', 'Polymer Class',
              'Characteristics of material', 'Material type', 'Polymerization informations',
              'Average molecular weights', 'Solvent', 'Non-solvent', 'Reference')
_DOI = re.compile(r'\b(10\.\d{4,9}/\S+)')


def _section(lines, start, stops):
    """lines 里从标题 start 之后到下一个 stops 之前的行。"""
    try:
        i = lines.index(start)
    except ValueError:
        return []
    out = []
    for ln in lines[i + 1:]:
        if ln.strip() in stops:
            break
        out.append(ln)
    return out


def parse_sample_info(text):
    """样品详情页 → {info{}, reference, doi, components[], composition[], properties[], related_tables[]}。
    related_tables 是原文的「组成 vs 性质」表（每张：title, header[], rows[[]]）—— 最值钱的那块，原样给。"""
    lines = [ln.rstrip() for ln in (text or '').splitlines()]
    heads = ('Information:', 'Component:', 'Composition:', 'Property:', 'Related Information:', 'Links')
    info, key = {}, None
    for ln in _section(lines, 'Information:', heads):
        m = re.match(r'^\t?([A-Za-z][A-Za-z \-]+):\t(.*)$', ln)
        if m and m.group(1).strip() in _INFO_KEYS:
            key = m.group(1).strip()
            info[key] = m.group(2).strip()
        elif key and ln.strip():
            info[key] = (info[key] + '\n' + ln.strip()).strip()
    ref = info.get('Reference') or ''
    doi = _DOI.search(ref)
    out = {'info': info, 'reference': ref.split('\n')[0] or None, 'doi': doi.group(1).rstrip('.') if doi else None,
           'components': [], 'composition': [], 'properties': [], 'related_tables': []}
    comp = [ln.split('\t') for ln in _section(lines, 'Component:', heads) if '\t' in ln]
    if comp:
        cols = [c.strip() for c in comp[0] if c.strip()]
        rows = {r[0].strip(): [c.strip() for c in r[1:]] for r in comp[1:] if r and r[0].strip()}
        for j in range(len(cols)):
            out['components'].append({k: (v[j] if j < len(v) else None) for k, v in rows.items()})
    cmp_rows = [ln.split('\t') for ln in _section(lines, 'Composition:', heads) if '\t' in ln]
    if len(cmp_rows) >= 2:
        ids = [c.strip() for c in cmp_rows[0][1:]]
        vals = [c.strip() for c in cmp_rows[1][1:]]
        unit = (re.search(r'\[(.*?)\]', cmp_rows[1][0]) or [None, None])[1]
        out['composition'] = [{'cuid': i, 'value': _num(v), 'unit': unit} for i, v in zip(ids, vals)]
    group = None
    for ln in _section(lines, 'Property:', heads):
        cells = [c.strip() for c in ln.split('\t') if c.strip()]
        if not cells:
            continue
        if not ln.startswith('\t') and len(cells) == 1:
            group = cells[0]
            continue
        if len(cells) >= 2:
            name, val = cells[0], cells[1]
            if name.startswith('Measurement') and out['properties']:
                out['properties'][-1][name.lower().replace(' ', '_')] = val
                continue
            m = re.match(r'^([-+]?[\d.]+(?:e[-+]?\d+)?)\s*\[(.*)\]$', val, re.I)
            out['properties'].append({'group': group, 'name': name, 'value': _num(m.group(1)) if m else None,
                                      'unit': m.group(2) if m else None, 'raw': val})
    tbl = None
    for ln in _section(lines, 'Related Information:', ('Links',)):
        if not ln.strip():
            continue
        if not ln.startswith('\t'):
            tbl = {'title': ln.strip(), 'header': None, 'rows': []}
            out['related_tables'].append(tbl)
            continue
        if tbl is None:
            continue
        cells = [c.strip() for c in ln.split('\t')[1:]]
        if tbl['header'] is None:
            tbl['header'] = cells
        else:
            tbl['rows'].append(cells)
    return out


def _result(**kw):
    r = {'ok': False, 'code': 'OK', 'page_kind': None, 'url': '', 'why': '', 'warnings': []}
    r.update(kw)
    return r


# ══════════════════════════════════════════════════════════════════════
# 浏览器
# ══════════════════════════════════════════════════════════════════════
# 自己连（同 chemdb）：不借 pdf_fetch._connect —— 那个会清扫多余标签。每次调用连上、用完就断。
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
                f'连不上主力机的「取全文用的浏览器」（{target}）：{e}。它要开着，PoLyInfo 要在里面登录过。')
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        yield browser, ctx
    finally:
        try:
            pw.stop()                     # 只断开连接，不关浏览器、不关标签
        except Exception:
            pass


def _find_tab(ctx):
    mine = [p for p in ctx.pages if HOST in (p.url or '') or is_login(p.url or '')
            and 'polymer.nims' in (p.url or '')]
    return mine[-1] if mine else None


def _tab(browser, ctx):
    """PoLyInfo 专用的标签：已有就复用（登录状态在上面），没有就后台开一个。"""
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


def _settle(pg, ready, timeout=40):
    """等到 ready(text) 为真且正文长度两次不变 → 是否等到。验证码出现也算「等到了」（交给调用方判）。"""
    end, prev = time.time() + timeout, -1
    while time.time() < end:
        t = _body(pg)
        if (ready(t) or is_captcha(t)) and len(t) == prev:
            return True
        prev = len(t)
        pg.wait_for_timeout(1200)
    return False


def _gate(pg, warnings):
    """当前页是登录页 / 验证码 → 对应的结果（页面原样留着给人处理）；都不是 → None。"""
    url = pg.url or ''
    if is_login(url):
        return _result(code='LOGIN_REQUIRED', page_kind='login', url=url, warnings=warnings,
                       why='PoLyInfo 要重新登录：请人在主力机「取全文用的浏览器」里点 Login with DICE account 登录')
    if is_captcha(_body(pg)):
        return _result(code='CAPTCHA_REQUIRED', page_kind=page_kind(url), url=url, warnings=warnings,
                       why='PoLyInfo 弹了人机验证：请人在主力机浏览器的 PoLyInfo 标签里输入图片里的字符并提交，'
                           '之后用 polyinfo_current 读这一页（不用重查）')
    return None


def _open_search(pg, warnings):
    try:
        pg.goto(SEARCH_URL, wait_until='load', timeout=60000)
    except Exception as e:
        return _result(code='NAVIGATE_FAILED', url=pg.url, warnings=warnings, why=f'打不开检索页：{str(e)[:120]}')
    _settle(pg, lambda t: 'POLYMER SEARCH' in t, timeout=30)
    return _gate(pg, warnings)


def _run_search(pg, name, pid, formula, prop, atoms_only, warnings):
    """在检索页上填表、点 POLYMER SEARCH，等结果列表。→ 失败时的结果 dict，成功 None。"""
    boxes = [e for e in pg.query_selector_all('input[type=text]') if e.is_visible()]
    if len(boxes) < 2:
        return _result(code='NAVIGATE_FAILED', url=pg.url, warnings=warnings, why='检索页没找到输入框（改版了？）')
    if pid:
        boxes[0].fill(pid)
    if name:
        boxes[1].fill(name)
    pairs = formula_counts(formula)
    if pairs:
        sels = [e for e in pg.query_selector_all('select[name=p-cu-atom1]') if e.is_visible()]
        for sel, (el, n) in zip(sels, pairs):
            sel.select_option(label=el)
            cnt = sel.evaluate_handle('s => { let n = s.nextElementSibling; while (n && n.tagName !== "INPUT") '
                                      'n = n.nextElementSibling; return n || s.parentElement.querySelector("input"); }')
            el_in = cnt.as_element()
            if el_in:
                el_in.fill(n)
        if atoms_only:
            box = pg.query_selector('#chx-search-atoms-only')
            if box and not box.is_checked():
                box.check()
    if prop:
        try:
            pg.locator('#property1_name_part').select_option(label=prop)
        except Exception:
            opts = pg.evaluate("[...document.querySelectorAll('#property1_name_part option')].map(o => o.text)")
            return _result(code='NOT_FOUND', url=pg.url, warnings=warnings,
                           why=f'没有这个性质「{prop}」；可选的有：' + ' / '.join(o for o in opts if o != 'not specified'))
    pg.locator('a.pi-body__pi-button', has_text='POLYMER SEARCH').first.click()
    if not _settle(pg, lambda t: bool(_MATCHES.search(t)), timeout=45):
        return _gate(pg, warnings) or _result(code='TIMEOUT', url=pg.url, warnings=warnings, why='结果列表 45 秒没出来')
    return _gate(pg, warnings)


def _list_result(pg, warnings):
    t = _body(pg)
    got = parse_list(t)
    code = 'OK' if got['items'] else 'NO_RESULTS'
    pages = len(pg.query_selector_all('a.page-link.page_btn')) // 2 or 1      # 分页条上下各一份
    return _result(ok=True, code=code, page_kind='polymer_list', url=pg.url, warnings=warnings,
                   pages=pages, page=1, **got)


def search(name='', pid='', formula=None, prop='', atoms_only=False):
    """检索一次 → 结果列表第 1 页。name = 聚合物名的子串（英文 IUPAC 式写法，如 poly(methyl methacrylate)）；
    pid = PID / COID / BDID；formula = 一个重复单元的分子式（'C16H38O5Si4' 或 {'C': 16, ...}，最多 6 种元素）；
    prop = 性质名，照检索页下拉框的写法（如 'Glass transition temperature'、'Density'）。"""
    if pid:
        pid = check_id(pid)
    if not (name or pid or formula):
        raise ValueError('name / pid / formula 至少给一个')
    formula_counts(formula)                     # 先在本地校验，别跑去网站才报错
    warnings = []
    with _session() as (browser, ctx):
        pg = _tab(browser, ctx)
        bad = _gate(pg, warnings) if pg.url and pg.url != 'about:blank' else None
        if bad:
            return bad                           # 验证码 / 登录页挡着：不覆盖它，留给人
        bad = _open_search(pg, warnings) or _run_search(pg, name, pid, formula, prop, atoms_only, warnings)
        if bad:
            return bad
        r = _list_result(pg, warnings)
        r['query'] = {'name': name or None, 'pid': pid or None, 'formula': formula or None, 'prop': prop or None}
        return r


def _to_samples(pg, pid, warnings):
    bad = _open_search(pg, warnings) or _run_search(pg, '', pid, None, '', False, warnings)
    if bad:
        return bad
    link = pg.locator(f'a.samples_link[data-pid="{pid}"]')
    if link.count() == 0:
        return _result(code='NOT_FOUND', url=pg.url, warnings=warnings, why=f'PoLyInfo 里没有 {pid}')
    link.first.click()
    if not _settle(pg, lambda t: 'Number of data points' in t, timeout=40):
        return _gate(pg, warnings) or _result(code='TIMEOUT', url=pg.url, warnings=warnings, why='样品列表 40 秒没出来')
    return _gate(pg, warnings)


def samples(pid):
    """一种聚合物的样品列表：每个样品的编号、材料类型、各项性质值（不含组成与出处 —— 那在 sample()）。"""
    pid = check_id(pid)
    warnings = []
    with _session() as (browser, ctx):
        pg = _tab(browser, ctx)
        bad = _gate(pg, warnings) if pg.url and pg.url != 'about:blank' else None
        if bad:
            return bad
        bad = _to_samples(pg, pid, warnings)
        if bad:
            return bad
        got = parse_samples(_body(pg))
        n_pages = len(pg.query_selector_all('a.page-link.page_btn')) // 2 or 1
        if n_pages > 1:
            warnings.append(f'样品列表有 {n_pages} 页，这里只读了第 1 页')
        return _result(ok=True, code='OK' if got['samples'] else 'NO_RESULTS', page_kind='sample_list',
                       url=pg.url, warnings=warnings, pid=pid, **got)


def sample(pid, n=1):
    """第 n 个样品（从 1 数，照 samples() 的 no）的详情：组成、聚合条件、分子量、出处、原文的组成–性质表。
    这一页网站要人机验证：撞上就回 CAPTCHA_REQUIRED，页面留在那里，人点完后用 current() 读。"""
    pid = check_id(pid)
    n = int(n)
    warnings = []
    with _session() as (browser, ctx):
        pg = _tab(browser, ctx)
        bad = _gate(pg, warnings) if pg.url and pg.url != 'about:blank' else None
        if bad:
            return bad
        bad = _to_samples(pg, pid, warnings)
        if bad:
            return bad
        rows = pg.locator('a.sample_list_row_sample_id')
        if rows.count() < n or n < 1:
            return _result(code='NOT_FOUND', url=pg.url, warnings=warnings,
                           why=f'{pid} 第 1 页只有 {rows.count()} 个样品（要第 {n} 个）')
        rows.nth(n - 1).click()
        _settle(pg, lambda t: 'Sample ID:' in t, timeout=40)
        bad = _gate(pg, warnings)
        if bad:
            return bad
        return _info_result(pg, warnings)


def _info_result(pg, warnings):
    got = parse_sample_info(_body(pg))
    if not got['info']:
        return _result(code='TIMEOUT', page_kind='sample_info', url=pg.url, warnings=warnings, why='样品详情没读到内容')
    return _result(ok=True, code='OK', page_kind='sample_info', url=pg.url, warnings=warnings, sample=got)


def current():
    """不导航：读 PoLyInfo 标签上现在那一页（结果列表 / 样品列表 / 样品详情各按各的解析）。"""
    warnings = []
    with _session() as (browser, ctx):
        pg = _find_tab(ctx)
        if not pg:
            return _result(code='NOT_FOUND', why='浏览器里没有 PoLyInfo 的标签')
        bad = _gate(pg, warnings)
        if bad:
            return bad
        kind = page_kind(pg.url)
        if kind == 'polymer_list':
            return _list_result(pg, warnings)
        if kind == 'sample_list':
            got = parse_samples(_body(pg))
            return _result(ok=True, code='OK', page_kind=kind, url=pg.url, warnings=warnings, **got)
        if kind == 'sample_info':
            return _info_result(pg, warnings)
        return _result(ok=True, code='OK', page_kind=kind, url=pg.url, warnings=warnings,
                       why='这一页不是结果页（检索页或别的），没什么可读')


def status():
    """PoLyInfo 标签现在停在哪、要不要登录、有没有验证码挡着 —— 只看浏览器，不碰网站。"""
    with _session() as (browser, ctx):
        pg = _find_tab(ctx)
        if not pg:
            return {'tab_open': False, 'url': '', 'page_kind': None, 'login_page': False, 'captcha': False}
        return {'tab_open': True, 'url': pg.url, 'page_kind': page_kind(pg.url),
                'login_page': is_login(pg.url), 'captcha': is_captcha(_body(pg))}
