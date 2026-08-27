# -*- coding: utf-8 -*-
"""adapters.openalex —— OpenAlex 学术检索 API（免费、无需密钥）。

**为什么要有这一块**（重构阶段 2）：

重构前，同一个 OpenAlex API 被**三个地方各自实现了一遍**：

    adapters/snowball          有退避重试、有礼貌 UA、有字段裁剪  ← 实现最好
    pipelines/paper_discovery  裸 urlopen，无重试
    找新文献/find_papers.py     裸 urlopen，无重试，又抄了一遍摘要还原

三份实现意味着三种行为：OpenAlex 一限流，snowball 会退避重试，另外两个直接失败。
而且**字段名各叫各的**，于是出了一个只在特定路径下才发作的 bug（见下）。

现在：HTTP、重试、摘要还原、字段归一，只有这一个文件负责。

## 统一的文献字典（与 adapters.sciverse 同构，全平台通用）

    {'title', 'doi', 'year', 'venue', 'citations', 'abstract',
     'is_oa', 'oa_url', 'openalex_id', 'first_author'}

⚠ 引用数的字段名是 **`citations`**。这一点曾经出过事：
`paper_discovery` 发的是 `cited_by`，而 `discover.py` 读的是 `cited` ——
两边都不是 `citations`，也互相对不上，结果走 OpenAlex 检索时
**引用数永远是 0**，还连累了按被引排序的打分。三处实现各写各的，就会这样。

## 用法

```python
from adapters import openalex

items, total = openalex.search('polyborosiloxane', limit=25)
w = openalex.work_by_doi('10.1021/xxxx')       # 查不到返回 None
```

OpenAlex 官方建议在 User-Agent 或 mailto 里带联系方式，可进「礼貌池」享更好配额。
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from core import errors

BASE = 'https://api.openalex.org'
UA = {'User-Agent': 'zotero-literature-platform (research tool)'}
# 只取用得上的字段：响应小一个数量级，也更快
FIELDS = ('id,doi,title,publication_year,cited_by_count,primary_location,'
          'abstract_inverted_index,open_access,authorships')

_RETRIABLE = (429, 500, 502, 503, 504)


def get(url, timeout=45, retries=2):
    """GET 一个 OpenAlex 地址，返回解析后的 JSON。

    429/5xx 会退避重试 —— 批量跑时必然撞上限流，不重试就是白跑一趟。
    失败时抛 `core.errors` 里的分类异常，调用方可以据此决定要不要再等。
    """
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}'
            if e.code in _RETRIABLE and attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            if e.code == 429:
                raise errors.RateLimited('OpenAlex 限流', service='openalex') from e
            if e.code in _RETRIABLE:
                raise errors.ExternalServiceError(
                    f'OpenAlex {last}', service='openalex') from e
            raise errors.ExternalServiceError(
                f'OpenAlex 拒绝了请求（{last}）', service='openalex') from e
        except Exception as e:
            last = f'{type(e).__name__}: {e}'
            if attempt < retries:
                time.sleep(2)
                continue
    raise errors.ExternalServiceError(
        f'OpenAlex 请求失败: {last}', service='openalex')


def restore_abstract(inv, limit=1500):
    """OpenAlex 的摘要是倒排索引（词 → 位置列表），还原成正常文本。

    这是 OpenAlex 为规避版权做的历史设计。不还原摘要就没法用 ——
    而摘要正是判断「这篇跟我的方向相不相关」的主要依据。
    """
    if not inv:
        return ''
    try:
        pos = {}
        for word, idxs in inv.items():
            for i in idxs:
                pos[i] = word
        return ' '.join(pos[i] for i in sorted(pos))[:limit]
    except Exception:
        return ''      # 摘要还原失败不该让整次检索失败


def normalize(w):
    """OpenAlex 的 work → 本平台统一的文献字典。"""
    loc = w.get('primary_location') or {}
    src = (loc.get('source') or {}) if isinstance(loc, dict) else {}
    doi = (w.get('doi') or '').replace('https://doi.org/', '')
    auth = w.get('authorships') or []
    try:
        first_author = auth[0]['author']['display_name'] if auth else ''
    except Exception:
        first_author = ''
    is_oa = bool((w.get('open_access') or {}).get('is_oa'))
    if not is_oa and isinstance(loc, dict):
        is_oa = bool(loc.get('is_oa'))
    return {
        'title': (w.get('title') or '').strip(),
        'doi': doi,
        'year': w.get('publication_year'),
        'venue': src.get('display_name') or '',
        'citations': w.get('cited_by_count') or 0,     # ← 全平台统一叫 citations
        'abstract': restore_abstract(w.get('abstract_inverted_index')),
        'is_oa': is_oa,
        'oa_url': (loc.get('landing_page_url') or '') if isinstance(loc, dict) else '',
        'openalex_id': (w.get('id') or '').split('/')[-1],
        'first_author': first_author,
    }


def search(query, limit=25, year_from=None, mailto='research@example.com'):
    """按检索词搜 OpenAlex。

    返回 `(items, total)`：items 是归一化后的文献列表，
    total 是 OpenAlex 报告的命中总数（用来告诉用户「共 N 篇，返回前 M 篇」）。
    """
    if not (query or '').strip():
        raise errors.BadInputError('检索词不能为空')
    params = [
        ('search', query),
        ('per-page', str(max(1, min(int(limit), 200)))),   # OpenAlex 单页上限 200
        ('sort', 'relevance_score:desc'),
        ('select', FIELDS),
        ('mailto', mailto),
    ]
    if year_from:
        params.append(('filter', f'from_publication_date:{int(year_from)}-01-01'))
    url = f'{BASE}/works?' + urllib.parse.urlencode(params)
    r = get(url)
    items = [normalize(w) for w in (r.get('results') or [])]
    total = ((r.get('meta') or {}).get('count')) or len(items)
    return items, total


def work_by_doi(doi):
    """按 DOI 取一篇文献。查不到返回 None（便于批量处理时直接跳过）。"""
    doi = (doi or '').strip().replace('https://doi.org/', '')
    if not doi:
        return None
    try:
        return get(f'{BASE}/works/doi:{urllib.parse.quote(doi)}')
    except errors.PlatformError:
        return None
