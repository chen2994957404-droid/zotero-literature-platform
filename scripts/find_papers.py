# -*- coding: utf-8 -*-
"""供Claude调用：按检索词去 OpenAlex 取真实文献，返回给Claude判断筛选。
用法: python find_papers.py "检索词" [数量]
"""
import urllib.request, json, urllib.parse, sys, io, re
# 强制utf-8输出，避免gbk编码错
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

query = sys.argv[1]
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 8

# 载入你库里已有文献的标题/DOI，用于标记"已有"
have_titles = set(); have_dois = set()
try:
    h = {'Zotero-Allowed-Request': 'true'}
    base = 'http://localhost:23119/api/users/16078117'
    s = 0
    while True:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(base+f'/items/top?limit=100&start={s}', headers=h), timeout=15).read())
        if not d: break
        for x in d:
            t = re.sub(r'[^a-z0-9]', '', (x['data'].get('title') or '').lower())
            if t: have_titles.add(t)
            if x['data'].get('DOI'): have_dois.add(x['data']['DOI'].lower())
        s += 100
        if len(d) < 100: break
except Exception:
    pass

url = ('https://api.openalex.org/works?search=' + urllib.parse.quote(query)
       + f'&per-page={limit}&sort=relevance_score:desc&mailto=research@example.com')
req = urllib.request.Request(url, headers={'User-Agent': 'research'})
r = json.loads(urllib.request.urlopen(req, timeout=30).read())

print(f'检索「{query}」共 {r["meta"]["count"]} 篇，返回 {len(r["results"])} 篇：\n')
for i, w in enumerate(r['results'], 1):
    doi = (w.get('doi') or '').replace('https://doi.org/', '')
    oa = (w.get('open_access') or {}).get('is_oa')
    venue = ''
    pl = w.get('primary_location')
    if pl and pl.get('source'):
        venue = pl['source'].get('display_name', '')
    # 作者
    auth = w.get('authorships', [])
    au_str = (auth[0]['author']['display_name'] + ' 等') if auth else ''
    # 摘要（OpenAlex用倒排索引存摘要，需还原）
    inv = w.get('abstract_inverted_index')
    abstract = ''
    if inv:
        words = {}
        for word, positions in inv.items():
            for p in positions:
                words[p] = word
        abstract = ' '.join(words[k] for k in sorted(words))[:220]
    # 判断是否库里已有
    tnorm = re.sub(r'[^a-z0-9]', '', (w.get('title') or '').lower())
    has = (tnorm in have_titles) or (doi.lower() in have_dois)
    flag = '【已在库】' if has else '【新】'
    print(f"{i}. {flag} [{w.get('publication_year')}] {w.get('title','')}")
    print(f"   {au_str} | {venue[:30]} | 引用{w.get('cited_by_count',0)} | {'OA可下' if oa else '需订阅'} | DOI:{doi}")
    if abstract:
        print(f"   摘要: {abstract}...")
    print()
