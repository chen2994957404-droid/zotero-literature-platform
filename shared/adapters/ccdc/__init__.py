# -*- coding: utf-8 -*-
"""ccdc · CCDC Access Structures（CSD / ICSD 单个晶体结构的免费查询）—— 借人登录好的浏览器，按人的节奏查、读页面

**为什么有这块（2026-10-09 用户定）**：查「某个含硼化合物有没有晶体结构、CCDC 号多少、出自哪篇」，
人查完截图给 Claude Science 太费事。用户原话：「我们都不是爬虫爬数据，就是跟 SciFinder 一样省去截图给
Claude Science 的过程，遇到人机验证我都会来点，也只做少量需要的检索」。

⚠ 条款（2026-10-09 读原文）：「Programmatic access to these services is not permitted」，并禁系统性检索与下载。
用户知情后决定按人的频率少量用（同 SciFinder 2026-10-08 的决定）。所以这块：
  - **一次只看一页、只读**：检索结果列表（最多 30 条）与单条详情。不下载 CIF、不翻全库、不批量看详情。
  - 撞验证页（「confirm you are not a robot」）→ 立刻回 CAPTCHA_REQUIRED，页面留给人；这里没有任何填验证码的代码。
  - 间隔与每天上限由调用方（host/mcp/science.py）强制，而且要低。

页面（2026-10-09 实测）：
  - 检索网址可以直接拼：/structures/Search?Compound=…&Ccdcid=…&Doi=…&Author=…&DatabaseToSearch=Published
  - 结果：每条一个 `input[type=checkbox][data-refcode][data-depositionnumber]`，所在行的文字有
    Space Group / Cell / Compound Name / Synonyms；最多 30 条（「returned more than 30 records」）
  - 点 `.refcode` → 右侧出详情：Deposition Number、Data Citation（数据 DOI 10.5517/…）、Deposited on、
    Associated publications（论文 DOI）。几何数据（键长）只在 CIF 里，这里不取。

对外接口：
  | 函数 | 说明 |
  |---|---|
  | `search(compound='', ident='', doi='', author='', database='Published')` | 检索 → 结果列表 |
  | `detail(n)` | 当前结果列表第 n 条（从 1 数）的详情 |
  | `current()` / `status()` | 不导航：读当前页 / 看验证码 |
  | `search_url` / `parse_results` / `parse_detail` / `is_captcha` | 纯函数（自测覆盖） |
"""
import contextlib
import re
import time
import urllib.parse

from shared.adapters import pdf_fetch
from shared.kernel.log import get_logger

log = get_logger('ccdc')

BASE = 'https://www.ccdc.cam.ac.uk/structures/'
DATABASES = {'Published': 'Published', 'CSD': 'CSD', 'ICSD': 'ICSD', 'Teaching': 'Teaching'}
MAX_ROWS = 30


# ══════════════════════════════════════════════════════════════════════
# 纯函数（自测覆盖）
# ══════════════════════════════════════════════════════════════════════

def search_url(compound='', ident='', doi='', author='', database='Published'):
    if database not in DATABASES:
        raise ValueError(f'database 只能是 {" / ".join(DATABASES)}（给了「{database}」）')
    q = {k: v.strip() for k, v in (('Ccdcid', ident), ('Compound', compound), ('Doi', doi), ('Author', author)) if v and v.strip()}
    if not q:
        raise ValueError('compound / ident（CCDC 号或结构代码）/ doi / author 至少给一个')
    q['DatabaseToSearch'] = database
    return BASE + 'Search?' + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)


def is_captcha(title, text):
    return 'validation request' in (title or '').lower() or 'not a robot' in (text or '').lower()


def _field(text, label):
    m = re.search(r'(?m)^\s*' + re.escape(label) + r':\s*(.+)$', text or '')
    return m.group(1).strip() if m else None


def parse_results(rows):
    """页面里抽出来的结果行 [{refcode, dep, icsd, text}] → [{rank, refcode, deposition, icsd, space_group, cell, name, synonyms}]。"""
    out = []
    for i, r in enumerate(rows or []):
        t = r.get('text') or ''
        dep = r.get('dep') or _field(t, 'Deposition Number(s)')
        out.append({'rank': i + 1, 'refcode': (r.get('refcode') or '').strip() or None,
                    'deposition': dep, 'icsd': (r.get('icsd') or '').strip() or None,
                    'space_group': _field(t, 'Space Group'), 'cell': _field(t, 'Cell'),
                    'name': _field(t, 'Compound Name'), 'synonyms': _field(t, 'Synonyms')})
    return out


_DOI = re.compile(r'DOI:\s*(10\.\d{4,9}/\S+)')


def parse_detail(text):
    """详情面板的文字 → {refcode, name, space_group, cell, deposition, data_doi, data_citation, deposited_on,
    synonyms, publications[{citation, doi}]}。"""
    t = text or ''
    out = {}
    m = re.search(r'(?m)^([A-Z]{6}\d{0,2})\s*:\s*(.+)$', t)
    if m:
        out['refcode'], out['name'] = m.group(1), m.group(2).strip()
    m = re.search(r'Space Group:\s*([^,\n]+(?:\(\d+\))?),\s*Cell:\s*(.+)', t)
    if m:
        out['space_group'], out['cell'] = m.group(1).strip(), m.group(2).strip()
    for label, key in (('Deposition Number', 'deposition'), ('Data Citation', 'data_citation'),
                       ('Synonyms', 'synonyms'), ('Additional Deposition Numbers', 'other_depositions'),
                       ('Deposited on', 'deposited_on'), ('Formula', 'formula')):
        m = re.search(r'(?m)^' + re.escape(label) + r'\t(.+)$', t)
        if m:
            out[key] = m.group(1).strip()
    if out.get('data_citation'):
        d = _DOI.search(out['data_citation'])
        out['data_doi'] = d.group(1).rstrip('.') if d else None
    pubs = []
    i = t.find('Associated publications')
    if i >= 0:
        for ln in t[i:].splitlines()[1:]:
            s = ln.strip()
            if not s:
                continue
            if s.startswith('Additional curated data') or s.startswith('CCDC Home'):
                break
            d = _DOI.search(s)
            pubs.append({'citation': s, 'doi': d.group(1).rstrip('.') if d else None})
    out['publications'] = pubs
    return out


def _result(**kw):
    r = {'ok': False, 'code': 'OK', 'url': '', 'why': '', 'warnings': [], 'items': []}
    r.update(kw)
    return r


# ══════════════════════════════════════════════════════════════════════
# 浏览器
# ══════════════════════════════════════════════════════════════════════

_ROWS_JS = """() => [...document.querySelectorAll('input[type=checkbox][data-refcode]')].map(cb => {
  const row = cb.closest('.row') || cb.parentElement;
  return {refcode: cb.getAttribute('data-refcode'), dep: cb.getAttribute('data-depositionnumber'),
          icsd: cb.getAttribute('data-icsdnumber'), text: row ? row.innerText : ''};
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
    mine = [p for p in ctx.pages if 'ccdc.cam.ac.uk/structures' in (p.url or '')]
    return mine[-1] if mine else None


def _tab(browser, ctx):
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
    except Exception:
        return ctx.new_page()


def _body(pg):
    try:
        return pg.evaluate('document.body ? document.body.innerText : ""') or ''
    except Exception:
        return ''


def _title(pg):
    try:
        return pg.title() or ''
    except Exception:
        return ''


def _gate(pg, warnings):
    if is_captcha(_title(pg), _body(pg)):
        return _result(code='CAPTCHA_REQUIRED', url=pg.url, warnings=warnings,
                       why='CCDC 弹了验证页（输入图片里的字并勾选同意条款）：请人在主力机「取全文用的浏览器」的 CCDC 标签里完成，'
                           '之后用 ccdc_current 读这一页（不用重查）')
    return None


def _settle(pg, ready, timeout=40):
    end, prev = time.time() + timeout, -1
    while time.time() < end:
        t = _body(pg)
        if is_captcha(_title(pg), t) or (ready(t) and len(t) == prev):
            return True
        prev = len(t)
        pg.wait_for_timeout(1200)
    return False


def _list_result(pg, warnings):
    t = _body(pg)
    items = parse_results(pg.evaluate(_ROWS_JS))
    more = 'more than 30 records' in t
    if more:
        warnings.append('more_than_30: 结果超过 30 条只显示前 30 条 —— 把检索词写具体些')
    q = re.search(r'Your query was:\s*(.+)', t)
    return _result(ok=True, code='OK' if items else 'NO_RESULTS', url=pg.url, warnings=warnings, items=items,
                   count=len(items), truncated=more, query_echo=q.group(1).strip() if q else None)


def search(compound='', ident='', doi='', author='', database='Published'):
    """检索一次 → 结果列表（最多 30 条）。compound = 化合物名（英文，如 phenylboronic acid）；
    ident = CCDC 号 / CSD 结构代码（如 740807、FUWHIP，可多个空格隔开）；doi = 一篇论文的 DOI；author = 作者。"""
    url = search_url(compound, ident, doi, author, database)
    warnings = []
    with _session() as (browser, ctx):
        pg = _tab(browser, ctx)
        if pg.url and 'ccdc' in pg.url:
            bad = _gate(pg, warnings)
            if bad:
                return bad
        try:
            pg.goto(url, wait_until='load', timeout=60000)
        except Exception as e:
            return _result(code='NAVIGATE_FAILED', url=url, warnings=warnings, why=f'打不开 CCDC：{str(e)[:120]}')
        _settle(pg, lambda t: 'Your query was' in t or 'no results' in t.lower() or 'No structures' in t, timeout=45)
        return _gate(pg, warnings) or _list_result(pg, warnings)


def detail(n):
    """当前结果列表第 n 条的详情（点它，读右侧面板）。"""
    n = int(n)
    warnings = []
    with _session() as (browser, ctx):
        pg = _find_tab(ctx)
        if not pg:
            return _result(code='NOT_FOUND', why='浏览器里没有 CCDC 的标签，先 search')
        bad = _gate(pg, warnings)
        if bad:
            return bad
        refs = pg.locator('.refcode')
        if refs.count() < n or n < 1:
            return _result(code='NOT_FOUND', url=pg.url, why=f'当前列表只有 {refs.count()} 条（要第 {n} 条）；先 search')
        want = parse_results(pg.evaluate(_ROWS_JS))[n - 1]['refcode']
        refs.nth(n - 1).click()
        _settle(pg, lambda t: 'Additional details' in t and (want or '') in t, timeout=40)
        bad = _gate(pg, warnings)
        if bad:
            return bad
        got = parse_detail(_body(pg))
        if want and got.get('refcode') and got['refcode'] != want:
            warnings.append(f'refcode_mismatch: 要 {want}，面板上是 {got["refcode"]}')
        return _result(ok=True, code='OK' if got.get('refcode') else 'TIMEOUT', url=pg.url, warnings=warnings, detail=got)


def current():
    warnings = []
    with _session() as (browser, ctx):
        pg = _find_tab(ctx)
        if not pg:
            return _result(code='NOT_FOUND', why='浏览器里没有 CCDC 的标签')
        bad = _gate(pg, warnings)
        if bad:
            return bad
        t = _body(pg)
        if 'Additional details' in t:
            return _result(ok=True, code='OK', url=pg.url, warnings=warnings, detail=parse_detail(t))
        if 'Your query was' in t:
            return _list_result(pg, warnings)
        return _result(ok=True, code='OK', url=pg.url, warnings=warnings, why='这一页不是结果也不是详情')


def status():
    with _session() as (browser, ctx):
        pg = _find_tab(ctx)
        if not pg:
            return {'tab_open': False, 'url': '', 'captcha': False}
        return {'tab_open': True, 'url': pg.url, 'captcha': is_captcha(_title(pg), _body(pg)),
                'signed_in': 'Sign In' not in _body(pg)[:400]}
