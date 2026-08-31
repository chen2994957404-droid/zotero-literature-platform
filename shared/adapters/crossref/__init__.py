# -*- coding: utf-8 -*-
"""crossref · DOI 元数据基础件（公理：一个 DOI → 这篇文献的书目信息）

**为什么有这块（R3 窗 2026-08-30 建）**：按 DOI 收文献进 Zotero 时要先拿到
标题/作者/期刊/年份。这段 HTTP 原本直接写在「找新文献/import_by_doi.py」里 ——
那是「联网只在 adapters」这条红线的破口（红线 #5）。
换掉元数据源（Crossref → DataCite / OpenAlex）本该只改一个文件。

Crossref 免费、无需密钥。礼貌起见 User-Agent 带项目名（官方推荐做法）。

对外接口：
  - work(doi)            → Crossref 的 message 原始字典；查不到抛 CrossrefError
  - to_zotero_item(m, tags) → message → Zotero journalArticle 条目字典

`to_zotero_item` 放在这里而不是调用方：**字段名对齐属于「外部世界长什么样」**，
Crossref 换字段就只改这一个文件。

依赖：Python 标准库 + shared.kernel.errors。
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from shared.kernel import errors

BASE = 'https://api.crossref.org'
UA = 'zotero-literature-platform/1.0'


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
