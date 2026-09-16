# -*- coding: utf-8 -*-
"""crossref · DOI 元数据基础件（原子能力：一个 DOI → 这篇文献的书目信息）

**为什么有这块（R3 窗 2026-08-30 建）**：按 DOI 收文献进 Zotero 时要先拿到
标题/作者/期刊/年份。这段 HTTP 原本直接写在「找新文献/import_by_doi.py」里 ——
那是「联网只在 adapters」这条强制规范的破口（强制规范 #5）。
换掉元数据源（Crossref → DataCite / OpenAlex）本该只改一个文件。

Crossref 免费、无需密钥。礼貌起见 User-Agent 带项目名（官方推荐做法）。

对外接口：
  - work(doi)            → Crossref 的 message 原始字典；查不到抛 CrossrefError
  - to_zotero_item(m, tags) → message → Zotero journalArticle 条目字典
  - journal_works_since(issn, since) → 这本刊从某天起新登记的文章（2026-09-15 加，给「盯新刊」用）
  - journal_works(issn, filters, cursor) → 按任意 filter 翻页取（回填几年用）
  - normalize(m)         → message → 本平台统一的文献字典（与 openalex.normalize 同形）

`to_zotero_item` 放在这里而不是调用方：**字段名对齐属于「外部世界长什么样」**，
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


def normalize(m):
    """Crossref message → 本平台统一的文献字典（字段名对齐 `openalex.normalize`）。

    只取「盯新刊 / 列清单」用得到的那几项；要收进 Zotero 走 `to_zotero_item`。
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
                          r'Author Correction|Publisher Correction|Editorial|Addendum)\b', re.I)


_SELECT = ('DOI,title,author,container-title,ISSN,publisher,type,issued,created,'
           'published-online,published-print,abstract,reference,is-referenced-by-count')


def _clean(items, types):
    out = [normalize(m) for m in items]
    if types:
        out = [w for w in out if w['type'] in types]
    # 更正 / 撤稿 / 勘误在 Crossref 里也是 journal-article，只能按标题认
    return [w for w in out if w['doi'] and w['title'] and not _NOT_A_PAPER.match(w['title'])]


def journal_works(issn, filters, rows=1000, cursor='*', types=('journal-article',), timeout=120):
    """一本刊按 Crossref filter 取**一页** → (items, next_cursor, total)。翻页把 next_cursor 传回来，
    没有下一页时 next_cursor 为 ''。filters 是 'from-pub-date:2023-09-15,until-pub-date:2026-09-15' 这种字符串。
    深翻页只能用 cursor（offset 上限 10000），所以回填三年用这个，别用 offset。
    """
    path = ('/journals/%s/works?filter=%s&rows=%d&cursor=%s&select=%s'
            % (urllib.parse.quote(str(issn).strip()), filters, min(int(rows), 1000),
               urllib.parse.quote(cursor, safe=''), _SELECT))
    msg = get(path, timeout=timeout)['message']
    items = msg.get('items') or []
    nxt = msg.get('next-cursor') or ''
    if len(items) < min(int(rows), 1000):
        nxt = ''                                      # 最后一页（Crossref 仍会给 cursor，别再翻）
    return _clean(items, types), nxt, msg.get('total-results') or 0


def journal_works_since(issn, since, rows=1000, types=('journal-article',), timeout=90):
    """一本刊（ISSN）从 `since`（YYYY-MM-DD）起**新登记**的文章 → [normalize 后的字典]。

    按 **登记日**（`from-created-date`）而不是出版日筛：出版社注册 DOI 的那一刻
    Crossref 就有了，比 OpenAlex 收录早几天到几周（2026-09-15 实测 Adv. Mater.
    一周：Crossref 91 篇 / OpenAlex 71 篇）—— 「盯新刊」要的就是这个最早时刻。

    `types` 只留正式论文（Nature/Science 的新闻、社论、勘误都在同一本刊下）。
    一页最多 1000 条；一本刊一周远到不了，超了就说明 `since` 给得太远，调用方缩窗口。
    """
    path = ('/journals/%s/works?filter=from-created-date:%s&rows=%d&sort=created&order=desc&select=%s'
            % (urllib.parse.quote(str(issn).strip()), since, min(int(rows), 1000), _SELECT))
    return _clean(get(path, timeout=timeout)['message'].get('items') or [], types)


def to_zotero_item(m, tags=None):
    """Crossref message → Zotero journalArticle 条目字典（可直接 POST）。

    tags 为空时不打任何标签 —— 是否触发精读由调用方单独决定（精读要花钱）。
    """
    creators = [{'creatorType': 'author',
                 'firstName': a.get('given', ''),
                 'lastName': a.get('family', a.get('name', ''))}
                for a in m.get('author', [])[:40]]
    date = ''
    for f in ('published-print', 'published-online', 'issued'):
        p = (m.get(f) or {}).get('date-parts', [[]])[0]
        if p:
            date = '-'.join(str(x) for x in p)
            break
    abstract = (m.get('abstract') or '')
    for junk in ('<jats:p>', '</jats:p>', '<jats:title>', '</jats:title>'):
        abstract = abstract.replace(junk, '')
    return {
        'itemType': 'journalArticle',
        'title': (m.get('title') or [''])[0],
        'creators': creators,
        'abstractNote': abstract.strip(),
        'publicationTitle': (m.get('container-title') or [''])[0],
        'volume': m.get('volume', ''), 'issue': m.get('issue', ''),
        'pages': m.get('page', ''), 'date': date,
        'DOI': m.get('DOI', ''), 'url': m.get('URL', ''),
        'libraryCatalog': 'Crossref',
        'tags': [{'tag': t} for t in (tags or [])],
    }
