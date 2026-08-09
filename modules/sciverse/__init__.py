# -*- coding: utf-8 -*-
"""sciverse · 全球文献库基础件（公理：查询 → 全球科学文献的结构化结果）

职责：把 OpenDataLab Sciverse 的能力封装成本平台可用的稳定接口。
Sciverse 是「科研 Agent 的可信证据数据层」：4.55 亿条记录、3000 万篇 AI-Ready 全文，
只返回**带出处的证据**，不生成答案 —— 生成由上层负责。

**为什么要包一层（关键设计判断）**：
Sciverse 尚处公测（官网有「抢先体验新接口与公测计划」字样），接口会变。
按架构宪法的首要判据：**发展中的东西用现成的，但必须把变化隔离在稳定接口背后**。
上层工作流只认本模块的四个函数；哪天官方改了字段或路径，只修这里，上层一行不动。

对外接口：
  - search_papers(query, ...)   → 结构化元数据列表（找新文献、按被引/年份精筛）
  - ask_evidence(question, ...) → 带原文片段与页码的证据列表（问全世界）
  - paper_relations(uid, ...)   → 某篇文献的引用/被引/相关工作
  - read_content(doc_id, ...)   → 按 doc_id 读全文上下文

依赖：Python 标准库 + modules.config（取 SCIVERSE_KEY）。
限流：官方默认 30 次/分钟，本模块对 429/5xx 自动退避重试。
"""
import os, sys, re, json, time, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from modules.config import get_key

BASE = 'https://api.sciverse.space'
DEFAULT_TIMEOUT = 90


class SciverseError(Exception):
    pass


def available():
    """是否已配置密钥。上层据此决定要不要走这条路，而不是直接报错。"""
    return bool(get_key('SCIVERSE_KEY'))


def _post(path, body, timeout=DEFAULT_TIMEOUT, retries=3):
    """统一请求：Bearer 鉴权 + 429/5xx 退避重试 + 可读错误。

    429 是限流（官方 30 次/分钟），退避等待比直接失败合理 ——
    批量补库时撞上限流是必然事件。4xx 是我们自己的错，立刻抛不浪费时间。
    """
    key = get_key('SCIVERSE_KEY')
    if not key:
        raise SciverseError('未配置 SCIVERSE_KEY。请在控制面板「Sciverse」一栏填写。')
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body, ensure_ascii=False).encode(),
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        method='POST')
    last = None
    for attempt in range(retries + 1):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        except urllib.error.HTTPError as e:
            body_txt = e.read()[:300].decode('utf8', 'replace')
            last = f'HTTP {e.code}: {body_txt}'
            if e.code == 429:                       # 限流：等待窗口恢复
                if attempt < retries:
                    time.sleep(20 * (attempt + 1))
                    continue
                raise SciverseError('触发 Sciverse 限流（默认 30 次/分钟），稍后再试')
            if e.code in (500, 502, 503, 504):
                if attempt < retries:
                    time.sleep(5 * 2 ** attempt)
                    continue
            if e.code == 401:
                raise SciverseError('Sciverse 密钥无效或已过期，请在控制面板重新填写')
            raise SciverseError(last)
        except Exception as e:
            last = f'{type(e).__name__}: {e}'
            if attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
    raise SciverseError(f'Sciverse 请求失败: {last}')


# 片段里混着 MinerU 风格的图片占位符与多余空白，直接给 LLM 会浪费 token 也干扰阅读
_IMG = re.compile(r'!\[\]\([^)]*\)')
_WS = re.compile(r'[ \t]*\n[ \t]*')


def clean_chunk(text):
    """清洗证据片段：去图片占位符、压缩空白。实测返回内容确实含这类噪声。"""
    if not text:
        return ''
    t = _IMG.sub('', text)
    t = _WS.sub('\n', t)
    return re.sub(r'\n{3,}', '\n\n', t).strip()


def looks_chinese(text):
    """是否含中文。用于提醒调用方：**中文检索式会显著降低召回质量**。

    实测：中文问「聚硼硅氧烷的剪切硬化机理」召回的是硼硅玻璃辐照、炉渣、LTCC 陶瓷
    （含「硼」但方向无关）；同一问题英文问，命中率与相关度都高得多。
    原因是服务端按 query 语言做语言亲和加权，而材料领域的高质量文献绝大多数是英文。
    """
    return any('一' <= c <= '鿿' for c in (text or ''))


def _year(v):
    """年份字段实测会返回 2022.0 这种浮点，也可能为 None。统一成 int 或 None。"""
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def search_papers(query, limit=25, year_from=None, year_to=None,
                  prefer='relevance', fields=None):
    """按主题检索全球文献元数据（不含正文片段）。

    prefer: 'relevance'(默认) / 'impact'(偏高被引) / 'fresh'(偏新) / 'citations'(按被引硬排)
    返回 list[dict]：title/doi/year/venue/citations/fwci/is_oa/oa_url/unique_id/doc_id/abstract
    """
    body = {'query': query, 'page_size': max(1, min(int(limit), 200)),
            'fields': fields or ['title', 'doi', 'abstract', 'author',
                                 'publication_published_year',
                                 'publication_venue_name_unified',
                                 'citation_count', 'fwci',
                                 'access_is_oa', 'access_oa_url', 'unique_id']}
    filters = []
    if year_from:
        filters.append({'field': 'publication_published_year',
                        'operator': 'FILTER_OP_GTE', 'value': int(year_from)})
    if year_to:
        filters.append({'field': 'publication_published_year',
                        'operator': 'FILTER_OP_LTE', 'value': int(year_to)})
    if filters:
        body['filters'] = filters
    # 排序与加权互斥：传 sort 是硬排，boost 会被忽略（官方文档明确说明）
    if prefer == 'citations':
        body['sort'] = [{'field': 'citation_count', 'order': 'SORT_ORDER_DESC'}]
    elif prefer == 'impact':
        body['impact_boost'] = 'MILD'
    elif prefer == 'fresh':
        body['freshness_boost'] = 'STRONG'

    r = _post('/meta-search', body)
    out = []
    for it in r.get('results', []):
        authors = [a.get('name') for a in (it.get('author') or []) if isinstance(a, dict)]
        out.append({
            'title': (it.get('title') or '').replace('\\n', ' ').strip(),
            'doi': it.get('doi') or '',
            'year': _year(it.get('publication_published_year')),
            'venue': it.get('publication_venue_name_unified') or '',
            'authors': authors[:6],
            'citations': _year(it.get('citation_count')) or 0,
            'fwci': it.get('fwci'),
            'is_oa': str(it.get('access_is_oa')).lower() == 'true',
            'oa_url': it.get('access_oa_url') or '',
            'unique_id': it.get('unique_id') or '',
            'doc_id': it.get('doc_id') or '',
            'abstract': (it.get('abstract') or '')[:600],
        })
    return {'total': r.get('total_count', 0), 'items': out}


def ask_evidence(question, top_k=8, year_from=None, sub_queries=0):
    """向全球文献提一个科学问题，拿回**可引用的原文片段**（不生成答案）。

    这是本平台原本没有的能力：库内问答只能答「我读过的文献怎么说」，
    本函数回答「全世界的文献怎么说」，且每条都带文献标题、页码、相关度。
    """
    body = {'query': question[:4096], 'top_k': max(1, min(int(top_k), 100))}
    if sub_queries:
        body['sub_queries'] = max(0, min(int(sub_queries), 4))
    if year_from:
        body['filters'] = {'publication_published_year': {'gte': int(year_from)}}
    r = _post('/agentic-search', body)
    out = []
    for h in r.get('hits', []):
        out.append({
            'title': (h.get('title') or '').replace('\\n', ' ').strip(),
            'chunk': clean_chunk(h.get('chunk')),
            'score': round(float(h.get('score') or 0), 3),
            'page': h.get('page_no'),
            'year': _year(h.get('publication_published_year')),
            'venue': h.get('publication_venue_name_unified') or '',
            'citations': _year(h.get('citation_count')) or 0,
            'doc_id': h.get('doc_id') or '',
            'offset': h.get('offset'),
        })
    return out


def paper_relations(unique_id, relation='CITATIONS', page=1, page_size=25):
    """查一篇文献的引用脉络。

    relation: CITATIONS(谁引用了它) / REFERENCES(它引用了谁) / RELATED_WORKS(相关工作)
    注意：这里必须用 unique_id（形如 paper:10.xxxx/yyy），**不是 doc_id**。
    """
    rel = str(relation).upper()
    if rel not in ('CITATIONS', 'REFERENCES', 'RELATED_WORKS'):
        raise SciverseError(f'relation 只能是 CITATIONS/REFERENCES/RELATED_WORKS，收到 {relation}')
    r = _post('/meta-paper-relations', {
        'unique_id': unique_id, 'relation': rel,
        'page': max(1, int(page)), 'page_size': max(1, min(int(page_size), 200))})
    return {'total': r.get('total_count', 0),
            'pages': r.get('total_pages', 0),
            'items': r.get('items', [])}


def read_content(doc_id, offset=None, length=4000):
    """按 doc_id 读全文上下文（配合 ask_evidence 返回的 offset 定位原文）。"""
    body = {'doc_id': doc_id}
    if offset is not None:
        body['offset'] = int(offset)
        body['length'] = int(length)
    return _post('/content', body)
