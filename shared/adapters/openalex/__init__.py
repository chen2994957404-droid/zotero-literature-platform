# -*- coding: utf-8 -*-
"""shared.adapters.openalex —— OpenAlex 学术检索 API（免费、无需密钥）。

**为什么要有这一块**（重构阶段 2）：

重构前，同一个 OpenAlex API 被**三个地方各自实现了一遍**：

    （雪球扩展、找新文献、方向地图三处各一份；这三样 2026-10 都已删掉）

三份实现意味着三种行为：OpenAlex 一限流，snowball 会退避重试，另外两个直接失败。
而且**字段名各叫各的**，于是出了一个只在特定路径下才发作的 bug（见下）。

现在：HTTP、重试、摘要还原、字段归一，只有这一个文件负责。
2026-10-24 起只剩两个用户：作者 / 摘要索引（`tools/library/oaindex`，按 DOI 批量取）
与 Claude Science 的题名检索（`host/mcp/science`）；语义检索、前向引用、期刊指标随找文献整套删了。

## 统一的文献字典（全平台通用）

    {'title', 'doi', 'year', 'venue', 'citations', 'abstract', 'abstract_truncated',
     'is_oa', 'oa_status', 'publisher', 'oa_url', 'openalex_id', 'first_author'}

⚠ 引用数的字段名是 **`citations`**。这一点曾经出过事：
`paper_discovery` 发的是 `cited_by`，而 `discover.py` 读的是 `cited` ——
两边都不是 `citations`，也互相对不上，结果走 OpenAlex 检索时
**引用数永远是 0**，还连累了按被引排序的打分。三处实现各写各的，就会这样。

## 用法

```python
from shared.adapters import openalex

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

from shared.kernel import errors

BASE = 'https://api.openalex.org'
UA = {'User-Agent': 'literature-platform (research tool)'}

# ── API key（2026-02 起 OpenAlex 改成按量计费，见踩坑 #77）────────────
# 无 key：$0.10/天（约 1000 次 filter 查询）；免费 key：$1/天（约 10000 次）。
# 单价：单条 /works/W123 **免费且无限次** · list/filter $0.10/千次 · 全文搜索 $1/千次。
# key 在 openalex.org/settings/api 免费领，30 秒。没有也能跑，只是额度小 10 倍。
def api_key():
    try:
        from shared.kernel.config import get_key
        return get_key('OPENALEX_KEY') or ''
    except Exception:
        return ''


def _auth(url):
    """给 URL 挂上 api_key（有就挂）。key 从系统凭据库/环境变量读，不落盘。"""
    k = api_key()
    if not k:
        return url
    return url + ('&' if '?' in url else '?') + 'api_key=' + urllib.parse.quote(k)
# 只取用得上的字段：响应小一个数量级，也更快
FIELDS = ('id,doi,title,publication_year,cited_by_count,primary_location,'
          'abstract_inverted_index,open_access,authorships,primary_topic,topics,type')

_RETRIABLE = (429, 500, 502, 503, 504)


def get(url, timeout=45, retries=2):
    """GET 一个 OpenAlex 地址，返回解析后的 JSON。

    429/5xx 会退避重试 —— 批量跑时必然撞上限流，不重试就是白跑一趟。
    失败时抛 `shared.kernel.errors` 里的分类异常，调用方可以据此决定要不要再等。
    """
    last = None
    for attempt in range(retries + 5):
        if attempt > retries and not (last or '').startswith('HTTP 429'):
            break
        try:
            req = urllib.request.Request(_auth(url), headers=UA)
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}'
            body = ''
            if e.code == 429:
                try:
                    body = e.read().decode('utf-8', 'replace')[:400]
                except Exception:
                    body = ''
            # 语义检索的「每秒 1 次」限速和日额度用完都是 429，但处理完全不同（2026-09-26 实测：
            # 几个会话并发检索时撞的是前者，提示却写成「额度用尽等 UTC 午夜」，把人带沟里）。
            # 前者响应体写着 "per second" / retryAfter —— 多等几轮就好，不算失败
            if e.code == 429 and ('per second' in body or 'retryAfter' in body):
                if attempt < retries + 4:
                    time.sleep(1.5 + attempt)
                    continue
                raise errors.RateLimited('OpenAlex 语义检索限速（每秒 1 次），多个检索同时在跑；'
                                         '等几秒重试即可，不是额度用完', service='openalex') from e
            if e.code in _RETRIABLE and attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            if e.code == 429:
                hint = ('OpenAlex 额度用尽或限流。'
                        + ('已配 OPENALEX_KEY（$1/天），等 UTC 午夜重置，'
                           '或改用免费的单条端点 works_by_ids(..., singleton=True)'
                           if api_key() else
                           '**当前没有配 API key，日额度只有 $0.10**。'
                           '去 openalex.org/settings/api 免费领一个（30 秒），'
                           '额度提高 10 倍；填进控制面板的 OPENALEX_KEY'))
                raise errors.RateLimited(hint, service='openalex') from e
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

    `limit=0`（或 None）= **不截断**。

    ⚠ 为什么要有「不截断」这条路（2026-09-10）：截断是在调用方看到之前
    **替它做判断**，而被截掉的常常正是方法那一段 —— 这次实战里决定性的那条证据
    （「二苯基硅二醇 + 对甲苯硼酸回流 12 小时，90% 产率得到八元环」）
    就藏在一篇标题讲废水处理的文章摘要靠后的位置。
    列表预览可以截（省上下文），但**「我要完整看这一篇」时必须给全**。
    """
    if not inv:
        return ''
    try:
        pos = {}
        for word, idxs in inv.items():
            for i in idxs:
                pos[i] = word
        text = ' '.join(pos[i] for i in sorted(pos))
        return text[:limit] if limit else text
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
    _abs_full = restore_abstract(w.get('abstract_inverted_index'), limit=0)
    _abs_preview = _abs_full[:1500]
    return {
        'title': (w.get('title') or '').strip(),
        'doi': doi,
        'year': w.get('publication_year'),
        'venue': src.get('display_name') or '',
        'citations': w.get('cited_by_count') or 0,     # ← 全平台统一叫 citations
        # 摘要默认截断（列表预览要省上下文），但**要如实说出「还有更多」**——
        # 悄悄截断等于替调用方判断「剩下的不重要」，而剩下的常常是方法那一段。
        # 想看全的走 restore_abstract(..., limit=0) 或 tools.litsearch.abstract()。
        'abstract': _abs_preview,
        'abstract_truncated': len(_abs_full) > len(_abs_preview),
        'is_oa': is_oa,
        # 出版商与开放获取状态 —— **两条事实，不是判断**（2026-09-10 加）。
        # 用户的真实诉求：LLM 找文献总偏向开放获取的（因为它自己读得到），
        # 不去找付费的好刊。解法不是过滤 MDPI（那是替他判断），
        # 而是把「谁出版的、付不付费」递出去，让调用方自己按他的路线挑。
        # OpenAlex 在 work 上直接给这两个字段，零额外请求。
        'publisher': src.get('host_organization_name') or '',
        # 条目类型（article / review / preprint / dataset / peer-review …，2026-09-26 加）：
        # 审稿意见、数据集这类不是论文，检索端据此剔除（验收里它们占了不少逐篇判断的工夫）
        'type': w.get('type') or '',
        'oa_status': (w.get('open_access') or {}).get('oa_status') or '',
        'oa_url': (loc.get('landing_page_url') or '') if isinstance(loc, dict) else '',
        'openalex_id': (w.get('id') or '').split('/')[-1],
        'first_author': first_author,
        # OpenAlex 的学科分类（2026-09-16 加）：一篇最多 3 个 topic，各带 subfield / field。
        # 这是**普适的**领域信号 —— 盯新刊按它判「是不是软物质 / 高分子」，不看用户自己的库。
        'topics': [t.get('display_name') or '' for t in (w.get('topics') or [])][:3],
        'subfields': [((t.get('subfield') or {}).get('display_name') or '') for t in (w.get('topics') or [])][:3],   # 与 topics 同序：第 0 个就是首要
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
    """按 DOI 取一篇文献。**OpenAlex 里没有这篇**返回 None；限流 / 断网 / 服务出错照实抛。

    原来任何错误都回 None（2026-09-30 排查「出错不报错」）：限流时调用方看到的是「这篇不存在」，
    Claude Science 据此下结论。现在只有 404 才是「没有」。
    """
    doi = (doi or '').strip().replace('https://doi.org/', '')
    if not doi:
        return None
    try:
        return get(f'{BASE}/works/doi:{urllib.parse.quote(doi)}')
    except errors.ExternalServiceError as e:
        if 'HTTP 404' in str(e):
            return None
        raise


# ── 批量取用（方向地图那类「几百上千篇一起要」的活）────────────────────
# 为什么要有这个：一篇一请求的话，754 篇种子 + 3000 篇骨干参考文献 = 近 4000 次
# 往返，跑一次要半小时以上。OpenAlex 的 filter 支持用 | 一次问 40~50 个 id，
# 实测把同样的活压到 100 次请求以内。**这是编排层里最容易写错的地方之一**
# （分批、拼 URL、漏掉查不到的），所以收在适配器里只写一遍。
BATCH = 40
# 礼貌池：OpenAlex 官方建议带 mailto，配额明显更好。
# ⚠ 这一行是实测补上的：`search()` 一直带着 mailto，而批量取用**漏了**，
# 于是批量跑到几千条就撞限流 —— 同一个 API，两个入口两种待遇。
POLITE_MAILTO = 'research@example.com'
# 撞限流后的退避阶梯（秒）。比 get() 内部那两次重试更长 ——
# 内部重试对付的是偶发抖动，这里对付的是「已经被限流了，得真的等一会」。
_BACKOFF = (5, 15, 45)


def _batch_filter(kind, values, select, batch=BATCH, on_progress=None,
                  mailto=POLITE_MAILTO, allow_partial=False):
    """按 `kind:a|b|c` 分批查询，返回 {openalex短id: work}。

    ⚠ **默认严格：任何一批最终失败就抛异常，绝不静默返回残缺结果。**

    这条是踩出来的（踩坑 #76）：早先这里写的是 `except PlatformError: pass`，
    结果建 impact 窄带时打到几千条撞上限流，**3126 篇骨干文献静默丢失（30%）**，
    日志全绿、不报错，只是图悄悄少了三成。而且排查时我还先误判成
    「这些 id 在 OpenAlex 里查不到」—— 因为重查时仍在限流期内，
    单条端点却能取到，两个现象一叠加就把人带沟里去了。

    **判据：静默的部分成功比明确的失败危险得多。**
    宁可整个作业失败让人重跑，也不要产出一份看不出问题的残缺数据。

    allow_partial=True 时不抛，但会把失败批次的数量交给 on_progress 报出来 ——
    调用方必须自己把这个数字落进产物里，否则残缺同样不可见。
    """
    out, failed = {}, []
    vals = [v for v in values if v]
    for i in range(0, len(vals), batch):
        chunk = vals[i:i + batch]
        f = '%s:%s' % (kind, '|'.join(chunk))
        url = '%s/works?filter=%s&per-page=%d&select=%s&mailto=%s' % (
            BASE, urllib.parse.quote(f, safe=':|/.'), batch, select,
            urllib.parse.quote(mailto))
        ok = False
        for wait in _BACKOFF + (None,):
            try:
                for w in get(url).get('results', []):
                    out[w['id'].rsplit('/', 1)[-1]] = w
                ok = True
                break
            except errors.PlatformError:
                if wait is None:
                    break
                time.sleep(wait)
        if not ok:
            failed.extend(chunk)
        if on_progress:
            on_progress(min(i + batch, len(vals)), len(vals), len(out))
    if failed:
        msg = ('OpenAlex 批量取用有 %d / %d 条最终失败（多半是限流，等几分钟重跑）'
               % (len(failed), len(vals)))
        if not allow_partial:
            raise errors.ExternalServiceError(msg, service='openalex')
        if on_progress:
            on_progress(len(vals), len(vals), len(out))
    return out


def works_by_dois(dois, select=FIELDS, on_progress=None, allow_partial=False):
    """一批 DOI → {openalex短id: work}。DOI 会被规范化（去前缀、小写、非断行连字符）。"""
    norm = []
    for d in dois:
        d = (d or '').strip().lower().replace('https://doi.org/', '').rstrip('.')
        for ch in ('‑', '‐', '–'):   # 微信正文里的非断行连字符（踩坑）
            d = d.replace(ch, '-')
        if d:
            norm.append(d)
    return _batch_filter('doi', sorted(set(norm)), select, on_progress=on_progress,
                         allow_partial=allow_partial)


def works_by_ids(ids, select=FIELDS, on_progress=None, allow_partial=False,
                 singleton=False):
    """一批 OpenAlex 短 id（W123...）→ {短id: work}。

    singleton=True 时逐条走 `/works/W123` —— **那个端点免费且不限次**，
    代价是请求数等于条目数（慢，但不花额度）。额度告急或没配 key 时用它。
    """
    clean = [str(i).rsplit('/', 1)[-1] for i in ids if i]
    if singleton:
        return works_singleton(clean, select=select, on_progress=on_progress,
                               allow_partial=allow_partial)
    return _batch_filter('openalex', sorted(set(clean)), select,
                         on_progress=on_progress, allow_partial=allow_partial)


def works_singleton(ids, select=FIELDS, on_progress=None, allow_partial=True):
    """逐条取（`/works/W123`）。**免费、不限次**，但一条一个请求。

    存在的理由：2026-02 起 list/filter 查询要花额度，而单条端点不花。
    没有 API key 时，一天只够 ~1000 次 filter；用这条路能把同样的活跑完，
    只是慢。**它是额度耗尽后唯一还能走的通路。**
    """
    out, failed = {}, []
    uniq = sorted(set(str(i).rsplit('/', 1)[-1] for i in ids if i))
    for n, wid in enumerate(uniq, 1):
        try:
            w = get('%s/works/%s?select=%s' % (BASE, wid, select))
            out[w['id'].rsplit('/', 1)[-1]] = w
        except errors.PlatformError:
            failed.append(wid)
        if on_progress and n % 200 == 0:
            on_progress(n, len(uniq), len(out))
    if failed and not allow_partial:
        raise errors.ExternalServiceError(
            'OpenAlex 单条取用有 %d / %d 条失败' % (len(failed), len(uniq)),
            service='openalex')
    return out
