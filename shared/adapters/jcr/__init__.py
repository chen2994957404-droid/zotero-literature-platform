# -*- coding: utf-8 -*-
"""jcr · Journal Citation Reports（Clarivate）—— 一本刊的影响因子、分区、学科排名；借人登录好的浏览器，一次查一本

**为什么有这块（2026-10-09 用户定）**：判断一篇文献出处的分量、投稿选刊，要看 JIF 与分区；
人查完截图给 Claude Science 太费事。用户原话：「跟 SciFinder 一样省去截图给 Claude Science 的过程，
遇到人机验证我都会来点，也只做少量需要的检索」。

⚠ 条款（Clarivate Terms v3.3，2026-10-09 读原文）：禁抓取；未签 AI 附加协议不得把其数据用于 AI 系统；禁文本数据挖掘。
用户知情后决定按人的频率、一次一本地查。所以这块：**只查单本刊的期刊页**，不导出、不翻学科全表、不批量；
结果**不写进平台的期刊分级表**（`journals.json` 仍只用 OpenAlex 开放数据），只当场回给调用方。

页面（2026-10-09 实测）：首页 `#search-bar` 输入刊名 / ISSN → 下拉 `li.suggestion-item`（`p.journal-title` 是可点的标题）→
期刊页 `/jcr-jp/journal-profile?journal=<JCR 刊名>&year=<年>`，正文里有 ISSN、学科、出版商、`<年> JOURNAL IMPACT FACTOR`、
不含自引的 JIF、JCI、开放获取比例，以及「Rank by Journal Impact Factor」下每个学科的 排名 / 分区 / 百分位。
登录失效会跳到 access.clarivate.com/login。

对外接口：
  | 函数 | 说明 |
  |---|---|
  | `journal(q, year=None)` | 刊名 / 缩写 / ISSN → 期刊页的字段 |
  | `status()` | 标签在不在、是不是登录页 —— 只看浏览器 |
  | `parse_profile` / `pick_suggestion` / `is_login` | 纯函数（自测覆盖） |
"""
import contextlib
import re
import time
import urllib.parse

from shared.adapters import pdf_fetch
from shared.kernel.log import get_logger

log = get_logger('jcr')

HOME = 'https://jcr.clarivate.com/jcr/home'
PROFILE = 'https://jcr.clarivate.com/jcr-jp/journal-profile?journal={j}&year={y}'   # journal 收全称；year 空 = 最新一年
_ISSN = re.compile(r'^\d{4}-\d{3}[\dXx]$')


# ══════════════════════════════════════════════════════════════════════
# 纯函数（自测覆盖）
# ══════════════════════════════════════════════════════════════════════

def is_login(url):
    return 'access.clarivate.com/login' in (url or '') or '/login?' in (url or '')


def pick_suggestion(q, sugg):
    """下拉建议 [{title, issns[]}] 里挑：ISSN 对得上 > 刊名完全一样（不分大小写）> 第一个。→ 下标或 None。"""
    if not sugg:
        return None
    qn = (q or '').strip().lower()
    if _ISSN.match(qn):
        for i, s in enumerate(sugg):
            if qn.upper() in [x.upper() for x in s.get('issns') or []]:
                return i
    for i, s in enumerate(sugg):
        if (s.get('title') or '').strip().lower() == qn:
            return i
    return 0


def _after(lines, label):
    for i, ln in enumerate(lines):
        if ln.strip() == label:
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    return nxt.strip()
    return None


def _num(s):
    try:
        return float((s or '').replace(',', '').rstrip('%'))
    except ValueError:
        return None


_RANK = re.compile(r'CATEGORY\n(?P<cat>[^\n]+)\n(?P<rank>\d+/\d+)\nJCR YEAR\tJIF RANK\tJIF QUARTILE\tJIF PERCENTILE\n'
                   r'(?P<year>\d{4})\t(?P<rank2>\d+/\d+)\t(?P<q>Q[1-4]|N/A)\t\n(?P<pct>[\d.]+|N/A)')


def parse_profile(text):
    """期刊页文字 → {title, issn, eissn, publisher, editions, categories, year, jif, jif_no_self, jci, oa_pct, ranks[]}。
    ranks：每个学科最近一年的 {category, rank, quartile, percentile}（2023 年起按学科排，不分版）。"""
    t = (text or '').replace('\r', '')
    lines = t.split('\n')
    out = {'title': None, 'issn': _after(lines, 'ISSN'), 'eissn': _after(lines, 'EISSN'),
           'abbreviation': _after(lines, 'JCR ABBREVIATION'), 'publisher': _after(lines, 'PUBLISHER'),
           'edition': _after(lines, 'EDITION'), 'year': None, 'jif': None, 'jif_no_self': None, 'jci': None,
           'oa_pct': None, 'ranks': []}
    i = next((k for k, ln in enumerate(lines) if ln.strip() == 'ISSN'), None)
    if i:
        prev = [ln.strip() for ln in lines[:i] if ln.strip()]
        out['title'] = prev[-1] if prev else None
    m = re.search(r'(\d{4}) JOURNAL IMPACT FACTOR\n+\s*([\d.,]+|N/A)', t)
    if m:
        out['year'], out['jif'] = int(m.group(1)), _num(m.group(2))
    m = re.search(r'JOURNAL IMPACT FACTOR WITHOUT SELF CITATIONS\n+\s*([\d.,]+)', t)
    if m:
        out['jif_no_self'] = _num(m.group(1))
    m = re.search(r'Journal Citation Indicator \(JCI\)\n+\s*([\d.]+)', t)
    if m:
        out['jci'] = _num(m.group(1))
    m = re.search(r'% OF CITABLE OA\n+\s*([\d.]+%)', t)
    if m:
        out['oa_pct'] = _num(m.group(1))
    sec = t[t.find('Rank by Journal Impact Factor'):] if 'Rank by Journal Impact Factor' in t else ''
    end = re.search(r'Rank by JIF before 2023|Rank by Journal Citation Indicator', sec)
    sec = sec[:end.start()] if end else sec
    for r in _RANK.finditer(sec):
        out['ranks'].append({'category': r['cat'].strip(), 'year': int(r['year']), 'rank': r['rank2'],
                             'quartile': r['q'], 'percentile': _num(r['pct'])})
    if re.search(r'(?m)^\s*On Hold\s*$', t) or 'this journal was ‘On Hold’' in t or "this journal was 'On Hold'" in t:
        out['status'] = 'On Hold'          # JCR 发布时暂停评估，当年没有 JIF（2026-10-09 实测 ACS Appl. Mater. Interfaces）
    out['categories'] = [r['category'] for r in out['ranks']] or ([_after(lines, 'CATEGORY')] if _after(lines, 'CATEGORY') else [])
    return out


def _result(**kw):
    r = {'ok': False, 'code': 'OK', 'url': '', 'why': '', 'warnings': []}
    r.update(kw)
    return r


# ══════════════════════════════════════════════════════════════════════
# 浏览器
# ══════════════════════════════════════════════════════════════════════

_SUGG_JS = """() => [...document.querySelectorAll('li.suggestion-item')].filter(li => li.querySelector('p.journal-title'))
  .map(li => ({title: (li.querySelector('p.journal-title') || {}).innerText || '',
               issns: ((li.innerText || '').match(/\\d{4}-\\d{3}[\\dXx]/g) || [])}))"""


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
    mine = [p for p in ctx.pages if 'jcr.clarivate.com' in (p.url or '') or 'access.clarivate.com' in (p.url or '')]
    return mine[-1] if mine else None


def _body(pg):
    try:
        return pg.evaluate('document.body ? document.body.innerText : ""') or ''
    except Exception:
        return ''


def _wait(pg, ready, timeout=40):
    end, prev = time.time() + timeout, -1
    while time.time() < end:
        if is_login(pg.url):
            return False
        t = _body(pg)
        if ready(t) and len(t) == prev:
            return True
        prev = len(t)
        pg.wait_for_timeout(1200)
    return False


def _login(pg):
    return _result(code='LOGIN_REQUIRED', url=pg.url,
                   why='JCR 要重新登录：请人在主力机「取全文用的浏览器」里打开 jcr.clarivate.com 登录 Clarivate 账号')


def journal(q, year=None):
    """一本刊（刊名 / JCR 缩写 / ISSN）→ 期刊页的字段。year 不给 = 最新一年。"""
    q = (q or '').strip()
    if not q:
        raise ValueError('给刊名或 ISSN')
    warnings = []
    with _session() as (browser, ctx):
        pg = _find_tab(ctx)
        if not pg:
            return _result(code='LOGIN_REQUIRED', why='浏览器里没有 JCR 的标签：请人在主力机浏览器打开 jcr.clarivate.com 并登录')
        if is_login(pg.url):
            return _login(pg)
        if pg.locator('#search-bar').count() == 0:
            try:
                pg.goto(HOME, wait_until='load', timeout=60000)
            except Exception as e:
                return _result(code='NAVIGATE_FAILED', url=pg.url, why=f'打不开 JCR 首页：{str(e)[:120]}')
            _wait(pg, lambda t: 'leading journals' in t or 'Journal name' in t, timeout=30)
            if is_login(pg.url):
                return _login(pg)
        box = pg.locator('#search-bar').first
        box.click()
        box.fill('')
        box.type(q, delay=40)
        end = time.time() + 15
        sugg = []
        while time.time() < end and not sugg:
            pg.wait_for_timeout(800)
            sugg = pg.evaluate(_SUGG_JS)
        i = pick_suggestion(q, sugg)
        if i is None:
            return _result(code='NOT_FOUND', url=pg.url, why=f'JCR 里没有找到「{q}」（不在 SCIE / SSCI / ESCI / AHCI 里，或写法不对）')
        title = sugg[i]['title'].strip()
        if (title.lower() != q.lower()) and not _ISSN.match(q):
            warnings.append(f'picked_suggestion: 「{q}」没有完全同名的，取了下拉里的「{title}」；其他候选：'
                            + ' / '.join(s['title'] for j, s in enumerate(sugg) if j != i)[:200])
        # 不点下拉（Angular 页面上点击时灵时不灵，2026-10-09 实测）：认出正式刊名后直接开期刊页
        # 先清空再开：同一个前端应用里换刊，旧页面的字会留一会儿（2026-10-09 实测把上一本的「On Hold」读成了这一本的）
        try:
            pg.goto('about:blank', timeout=15000)
            pg.goto(PROFILE.format(j=urllib.parse.quote(title), y=int(year) if year else ''), wait_until='load', timeout=60000)
        except Exception as e:
            return _result(code='NAVIGATE_FAILED', url=pg.url, why=f'打不开期刊页：{str(e)[:120]}')
        want = title.lower()

        def _ready(t):
            head = t[:4000].lower()
            return want in head and ('JOURNAL IMPACT FACTOR' in t or 'On Hold' in t or 'Journal Citation Indicator (JCI)' in t)
        if not _wait(pg, _ready, timeout=45):
            if is_login(pg.url):
                return _login(pg)
            return _result(code='TIMEOUT', url=pg.url, warnings=warnings, why='期刊页 45 秒没出来')
        # 学科排名那段是滚到才加载的（2026-10-09 实测：不滚就一直没有「Rank by Journal Impact Factor」）
        end = time.time() + 25
        while time.time() < end and 'Rank by Journal Impact Factor' not in _body(pg):
            pg.evaluate('window.scrollBy(0, Math.max(800, window.innerHeight))')
            pg.wait_for_timeout(1000)
        got = parse_profile(_body(pg))
        if got.get('status') == 'On Hold':
            warnings.append('on_hold: JCR 发布时这本刊处于「On Hold」（暂停评估），没有当年的 JIF —— 去 Master Journal List 看现状')
        elif not got['ranks']:
            warnings.append('no_rank: 页面上没读到学科排名（ESCI 刊或页面没加载完）')
        return _result(ok=True, code='OK' if got.get('jif') is not None or got.get('ranks') or got.get('status') else 'NO_RESULTS',
                       url=pg.url, warnings=warnings, query=q, journal=got)


def status():
    with _session() as (browser, ctx):
        pg = _find_tab(ctx)
        if not pg:
            return {'tab_open': False, 'url': '', 'login_page': False}
        return {'tab_open': True, 'url': pg.url, 'login_page': is_login(pg.url)}
