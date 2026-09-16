# -*- coding: utf-8 -*-
"""semanticscholar · Semantic Scholar 学术图谱（2026-09-16 建）。

**它比 Crossref / OpenAlex 多给的三样**（2026-09-16 实测）：
  ① 引用意图：后人引这篇是当 background / methodology / result，附引用时的那句话（contexts）
     —— 「别人怎么用我库里这篇」，是 Crossref 的参考文献列表给不了的
  ② 被引数（比 Crossref 全，含预印本与会议）与开放获取 PDF 直链
  ③ 一句话摘要 TLDR —— 但材料领域覆盖不高（试的三篇都没有），别指望它

额度：免费 key 每秒 1 次（累计所有端点）；没 key 走公共池（每 5 分钟 100 次）。
key 从 `S2_API_KEY` 读（系统凭据库），放在请求头 `x-api-key`。本模块自己按 1 秒节流。

对外接口：
  - papers(dois, fields)        → {doi: 归一后的字典}（批量端点，一次最多 500 篇）
  - citations(doi, limit)       → [{doi, title, intents, contexts, year}]（谁引了它、怎么引的）
  - normalize(rec)              → 原始 JSON → 我们的字典（纯函数，自测用）
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from shared.kernel import errors
from shared.kernel.log import get_logger

BASE = 'https://api.semanticscholar.org/graph/v1'
UA = 'literature-platform/1.0'
FIELDS = 'externalIds,title,abstract,tldr,citationCount,openAccessPdf,publicationDate'
CITE_FIELDS = 'contexts,intents,citingPaper.externalIds,citingPaper.title,citingPaper.year'
BATCH = 500
_log = get_logger('semanticscholar')
_gate = {'last': 0.0, 'lock': threading.Lock()}


class S2Error(errors.ExternalServiceError):
    """Semantic Scholar 查询失败（限流 / 抖动，可重试）。"""


def api_key():
    try:
        from shared.kernel.config import get_key
        return get_key('S2_API_KEY') or ''
    except Exception:
        return ''


def _throttle():
    """全局 1 秒一次（key 的额度是「累计所有端点」，不分批量还是单条）。"""
    with _gate['lock']:
        wait = 1.05 - (time.time() - _gate['last'])
        if wait > 0:
            time.sleep(wait)
        _gate['last'] = time.time()


def _call(path, body=None, timeout=60, retries=3):
    hdr = {'User-Agent': UA, 'Content-Type': 'application/json'}
    k = api_key()
    if k:
        hdr['x-api-key'] = k
    data = json.dumps(body).encode('utf-8') if body is not None else None
    for i in range(retries):
        _throttle()
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + path, data=data, headers=hdr), timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 429 and i + 1 < retries:
                time.sleep(3 * (i + 1))
                continue
            try:
                detail = e.read().decode('utf-8', 'replace')[:160]
            except Exception:
                detail = ''
            raise S2Error(f'HTTP {e.code} {detail}') from e
        except Exception as e:
            if i + 1 < retries:
                time.sleep(2)
                continue
            raise S2Error(f'{type(e).__name__}: {e}') from e
    raise S2Error('重试用尽')


def normalize(rec):
    """S2 的 paper 记录 → 我们的字典。查不到（None）→ None。"""
    if not rec:
        return None
    ext = rec.get('externalIds') or {}
    return {
        'doi': (ext.get('DOI') or '').lower(),
        's2_id': rec.get('paperId') or '',
        'title': ' '.join((rec.get('title') or '').split()),
        'abstract': (rec.get('abstract') or '')[:3000],
        'tldr': ((rec.get('tldr') or {}).get('text') or '').strip(),
        'citations': rec.get('citationCount') or 0,
        'oa_pdf': ((rec.get('openAccessPdf') or {}).get('url') or ''),
        'published': rec.get('publicationDate') or '',
    }


def papers(dois, fields=FIELDS):
    """一批 DOI → {doi: 字典}。S2 没有的不在结果里。一次最多 500 篇，自动分批。"""
    out = {}
    ids = [d.strip().lower().replace('https://doi.org/', '') for d in dois if d and d.strip()]
    for i in range(0, len(ids), BATCH):
        chunk = ids[i:i + BATCH]
        res = _call('/paper/batch?fields=' + urllib.parse.quote(fields), body={'ids': ['DOI:' + d for d in chunk]}) or []
        for d, rec in zip(chunk, res):
            n = normalize(rec)
            if n:
                n['doi'] = n['doi'] or d
                out[d] = n
    return out


def citations(doi, limit=200):
    """谁引了这篇、怎么引的 → [{doi, title, year, intents, contexts}]。intents ∈ background / methodology / result。"""
    doi = (doi or '').strip().replace('https://doi.org/', '')
    rows, offset = [], 0
    while offset < limit:
        d = _call('/paper/DOI:%s/citations?fields=%s&limit=%d&offset=%d' % (
            urllib.parse.quote(doi, safe=''), urllib.parse.quote(CITE_FIELDS), min(100, limit - offset), offset))
        if not d:
            break
        for it in d.get('data') or []:
            cp = it.get('citingPaper') or {}
            rows.append({'doi': ((cp.get('externalIds') or {}).get('DOI') or '').lower(),
                         'title': cp.get('title') or '', 'year': cp.get('year'),
                         'intents': it.get('intents') or [], 'contexts': it.get('contexts') or []})
        if d.get('next') is None:
            break
        offset = d['next']
    return rows
