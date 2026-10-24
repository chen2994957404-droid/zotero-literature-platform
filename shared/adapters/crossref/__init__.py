# -*- coding: utf-8 -*-
"""crossref · DOI 元数据基础件（原子能力：一个 DOI → 这篇文献的书目信息）

**为什么有这块（R3 窗 2026-08-30 建）**：按 DOI 收文献时要先拿到
标题/作者/期刊/年份。这段 HTTP 原本直接写在「找新文献/import_by_doi.py」里 ——
那是「联网只在 adapters」这条强制规范的破口（强制规范 #5）。
换掉元数据源（Crossref → DataCite / OpenAlex）本该只改一个文件。

Crossref 免费、无需密钥。礼貌起见 User-Agent 带项目名（官方推荐做法）。

对外接口：
  - work(doi)            → Crossref 的 message 原始字典；查不到抛 CrossrefError
  - to_meta(m) → message → 目录卡要的扁平字段（标题 / 期刊 / 年份 / 作者 / 摘要）
  - normalize(m)         → message → 本平台统一的文献字典（与 openalex.normalize 同形）

`to_meta` 放在这里而不是调用方：**字段名对齐属于「外部世界长什么样」**，
Crossref 换字段就只改这一个文件。

依赖：Python 标准库 + shared.kernel.errors。
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from shared.kernel import errors

BASE = 'https://api.crossref.org'
UA = 'literature-platform/1.0'


class CrossrefError(errors.ExternalServiceError):
    """Crossref 查询失败。归入 ExternalServiceError：多半是对方的问题，可重试。"""


class DoiNotFound(CrossrefError):
    """这个 DOI 在 Crossref 里不存在 —— 重试没用，调用方应跳过这条。"""


def get(path, timeout=45):
    """GET 一个 Crossref 路径，返回解析后的 JSON。"""
    req = urllib.request.Request(BASE + path, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise DoiNotFound('Crossref 查不到这个 DOI') from e
        raise CrossrefError(f'HTTP {e.code}') from e
    except Exception as e:
        raise CrossrefError(f'{type(e).__name__}: {e}') from e


def work(doi):
    """按 DOI 取元数据（Crossref 的 message 字典）。DOI 不存在抛 DoiNotFound。"""
    doi = (doi or '').strip().replace('https://doi.org/', '')
    if not doi:
        raise DoiNotFound('空 DOI')
    return get('/works/' + urllib.parse.quote(doi))['message']


def title_similarity(a, b):
    """两个标题像不像（0–1）：只比字母数字，不管大小写、标点、<i> 标签。"""
    import difflib
    norm = lambda s: ' '.join(re.findall(r'[a-z0-9]+', re.sub(r'<[^>]+>', '', s or '').lower()))
    a, b = norm(a), norm(b)
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def match_title(title, year=None, author='', journal='', volume=''):
    """按标题（+ 年份、第一作者、刊名、卷）找 DOI → {doi, score, title, year, journal, volume, page} 或 None。

    给「只有标题没有 DOI」的列表用（SciFinder 的结果列表就是这样，2026-10-08）。
    score = 标题相似度；年份对不上扣 0.1。给了卷号时，标题一样像的候选里**卷号对得上的优先**：
    Angewandte 同一篇有德文版（卷 131）和国际版（卷 58），标题一字不差，只靠标题会配到德文版（2026-10-08 实测 13 条）。
    """
    q = {'query.bibliographic': title, 'rows': '5' if volume or journal else '3',
         'select': 'DOI,title,issued,container-title,volume,page'}
    if author:
        q['query.author'] = author
    if journal:
        q['query.container-title'] = journal
    items = get('/works?' + urllib.parse.urlencode(q), timeout=20)['message'].get('items') or []
    best, best_key = None, None
    for it in items:
        t = (it.get('title') or [''])[0]
        y = ((it.get('issued') or {}).get('date-parts') or [[None]])[0][0]
        s = title_similarity(title, t) - (0.1 if year and y and abs(int(y) - int(year)) > 1 else 0)
        vol_ok = bool(volume) and str(it.get('volume') or '') == str(volume)
        key = (round(s, 2) >= 0.9 and vol_ok, s)          # 标题够像时卷号对得上的排前面
        if best_key is None or key > best_key:
            best_key = key
            best = {'doi': (it.get('DOI') or '').lower(), 'score': round(s, 3), 'title': t, 'year': y,
                    'journal': (it.get('container-title') or [''])[0], 'volume': it.get('volume'), 'page': it.get('page')}
    return best


def normalize(m):
    """Crossref message → 本平台统一的文献字典（字段名对齐 `openalex.normalize`）。

    只取「列清单」用得到的那几项；要填目录卡走 `to_meta`。
    """
    def _date(*fields):
        for f in fields:
            p = ((m.get(f) or {}).get('date-parts') or [[]])[0]
            if p:
                return '-'.join('%02d' % int(x) if i else str(x) for i, x in enumerate(p))
        return ''
    abstract = m.get('abstract') or ''
    for junk in ('<jats:p>', '</jats:p>', '<jats:title>', '</jats:title>', '<jats:sec>', '</jats:sec>'):
        abstract = abstract.replace(junk, '')
    auth = m.get('author') or []
    first = auth[0].get('family') or auth[0].get('name') or '' if auth else ''
    return {
        'title': ' '.join(re.sub(r'<[^>]+>', '', (m.get('title') or [''])[0]).split()),   # ACS 标题里带 <i>co</i>
        'doi': (m.get('DOI') or '').lower(),
        'year': int(_date('issued', 'published-online', 'created')[:4] or 0) or None,
        'venue': (m.get('container-title') or [''])[0],
        'issn': (m.get('ISSN') or [''])[0],
        'publisher': m.get('publisher') or '',
        'type': m.get('type') or '',
        'published': _date('published-online', 'published-print', 'issued'),
        'created': _date('created'),          # DOI 登记日：最早能知道「它出来了」的时刻
        'abstract': abstract.strip()[:3000],
        'first_author': first,
        'authors': [(a.get('family') or a.get('name') or '') for a in auth[:60]],
        # 参考文献里带 DOI 的那些（0 级信息里最值钱的一项：引用网络、「引了我库里哪几篇」）
        'refs': sorted({(r.get('DOI') or '').lower() for r in (m.get('reference') or []) if r.get('DOI')}),
        'citations': m.get('is-referenced-by-count') or 0,
    }


_NOT_A_PAPER = re.compile(r'^(Correction|Corrigendum|Erratum|Retraction|Expression of Concern|'
                          r'Author Correction|Publisher Correction|Editorial|Addendum|'
                          r'Issue Publication Information|Issue Editorial Masthead|Masthead|'
                          r'Front Cover|Back Cover|Inside Cover|Cover Picture|Cover Feature|Table of Contents|New Products|Editors. Choice)\b', re.I)


_SELECT = ('DOI,title,author,container-title,ISSN,publisher,type,issued,created,'
           'published-online,published-print,abstract,reference,is-referenced-by-count')


def to_meta(m):
    """Crossref message → 目录卡要的扁平字段：title / journal / year / authors / abstract / volume / issue / pages。

    原来叫 `to_zotero_item`，拼的是 Zotero 的 journalArticle 条目；Zotero 移出平台后只剩「填目录卡」一个用处。
    """
    authors = []
    for a in m.get('author', [])[:40]:
        n = (a.get('family', a.get('name', '')) + ' ' + a.get('given', '')).strip()
        if n:
            authors.append(n)
    year = ''
    for f in ('published-print', 'published-online', 'issued'):
        p = (m.get(f) or {}).get('date-parts', [[]])[0]
        if p:
            year = str(p[0])
            break
    abstract = (m.get('abstract') or '')
    for junk in ('<jats:p>', '</jats:p>', '<jats:title>', '</jats:title>'):
        abstract = abstract.replace(junk, '')
    return {
        'title': (m.get('title') or [''])[0],
        'journal': (m.get('container-title') or [''])[0],
        'year': year,
        'authors': authors,
        'abstract': abstract.strip(),
        'volume': m.get('volume', ''), 'issue': m.get('issue', ''), 'pages': m.get('page', ''),
        'doi': m.get('DOI', ''),
    }
