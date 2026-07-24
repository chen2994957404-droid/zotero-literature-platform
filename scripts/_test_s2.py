# -*- coding: utf-8 -*-
"""测试 Semantic Scholar API：检索 + 基于已有文献的推荐。"""
import urllib.request, json, urllib.parse

def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'research-tool'})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

print('=== 1. 关键词检索 ===')
q = 'polyborosiloxane shear stiffening impact'
url = ('https://api.semanticscholar.org/graph/v1/paper/search?query=' + urllib.parse.quote(q)
       + '&limit=5&fields=title,year,externalIds,openAccessPdf,venue')
try:
    r = get(url)
    print('检索到', r.get('total'), '篇')
    for p in r.get('data', []):
        doi = (p.get('externalIds') or {}).get('DOI', '无')
        oa = p.get('openAccessPdf')
        print('  [%s] %s' % (p.get('year'), (p.get('title') or '')[:48]))
        print('     DOI:%s OA:%s' % (doi, 'YES' if oa else 'no'))
except Exception as e:
    print('检索失败:', e)

print('\n=== 2. 基于一篇文献的推荐 ===')
# 用一个DOI找它的推荐相关文献
try:
    # 先拿一篇的paperId
    doi = '10.1002/adma.74001'  # 你库里的Wei那篇
    p = get('https://api.semanticscholar.org/graph/v1/paper/DOI:' + doi + '?fields=title,paperId')
    pid = p['paperId']
    print('种子文献:', p['title'][:45])
    rec = get('https://api.semanticscholar.org/recommendations/v1/papers/forpaper/' + pid
              + '?limit=5&fields=title,year,externalIds,openAccessPdf')
    print('推荐的相关文献:')
    for x in rec.get('recommendedPapers', []):
        doi2 = (x.get('externalIds') or {}).get('DOI', '无')
        print('  [%s] %s (DOI:%s)' % (x.get('year'), (x.get('title') or '')[:45], doi2))
except Exception as e:
    print('推荐失败:', e)
