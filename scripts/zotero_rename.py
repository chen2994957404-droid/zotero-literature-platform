# -*- coding: utf-8 -*-
"""Zotero 附件统一命名：正文→Full Text PDF、SI→SI、网页快照→Snapshot。
数据源用全库JSON(快)，改名用Web API。
用法: python zotero_rename.py <全库json路径> [apply]
  不带apply=只分析(dry-run)；带apply=真正改
"""
import urllib.request, json, re, sys, time
try:
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
    from modules.config import get_key as _cfg_get
except Exception:
    _cfg_get = lambda n, **kw: _o.environ.get(n, '')

# 本机配置（Zotero 用户ID / 附件目录）统一从 modules.config 读，换电脑只改 .env
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
try:
    from modules.config import need_site as _site
except Exception:
    _site = lambda n: _os.environ.get(n) or (_ for _ in ()).throw(RuntimeError(f'缺少本机设置 {n}，请在控制面板或 .env 中配置'))
_UID = _site('ZOTERO_USER_ID')
_STORAGE = _site('ZOTERO_STORAGE')
USER_ID = _UID
WEB_KEY = _cfg_get('ZOTERO_API_KEY')
WEB = 'https://api.zotero.org/users/' + USER_ID
WH = {'Zotero-API-Key': WEB_KEY, 'Zotero-API-Version': '3'}

JSON_PATH = sys.argv[1]
APPLY = len(sys.argv) > 2 and sys.argv[2] == 'apply'

SUPP = re.compile(r'suppmat|supp[_\-\.]|supporting|supplement|[_\-]si[_\-\.]|_si_?\d|si[_\-]?\d{3}|appendix|支持信息|支持性信息|补充材料|补充信息', re.I)

def classify(d):
    ct = d.get('contentType', '')
    fn = d.get('filename') or ''
    title = d.get('title') or ''
    name = fn + ' ' + title
    lm = d.get('linkMode', '')
    if ct == 'text/html' or 'snapshot' in lm.lower():
        return 'Snapshot'
    if SUPP.search(name) or title.strip() == 'SI':
        return 'SI'
    if ct == 'application/pdf':
        return 'Full Text PDF'
    return None

def get_current(att_key):
    """实时取附件当前 version 和 title（避免用旧version冲突）"""
    req = urllib.request.Request(WEB + '/items/' + att_key, headers=WH)
    d = json.loads(urllib.request.urlopen(req, timeout=15).read())
    return d['version'], (d['data'].get('title') or d['data'].get('filename') or '')

def rename(att_key, new_title):
    """先取最新version再改，带429重试"""
    for attempt in range(4):
        try:
            ver, cur = get_current(att_key)
            if cur == new_title:
                return 'skip'
            patch = json.dumps({'title': new_title}).encode('utf-8')
            req = urllib.request.Request(WEB + '/items/' + att_key, data=patch, method='PATCH',
                headers={**WH, 'If-Unmodified-Since-Version': str(ver), 'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=15)
            return 'ok'
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get('Retry-After', 10))
                time.sleep(min(wait, 30)); continue
            if e.code == 412:  # version冲突，重取重试
                time.sleep(1); continue
            raise
    return 'fail'

items = json.load(open(JSON_PATH, encoding='utf-8'))
atts = [x for x in items if x['data'].get('itemType') == 'attachment' and x['data'].get('parentItem')]

from collections import Counter
stat = Counter()
changes = []
for a in atts:
    d = a['data']
    tgt = classify(d)
    cur = d.get('title') or d.get('filename') or ''
    if tgt is None:
        stat['跳过'] += 1; continue
    if cur == tgt:
        stat['已符合'] += 1; continue
    stat[tgt] += 1
    changes.append((a['key'], a['version'], cur, tgt))

print('子附件总数:', len(atts))
print('待改 Full Text PDF:', stat['Full Text PDF'], '| SI:', stat['SI'], '| Snapshot:', stat['Snapshot'])
print('已符合:', stat['已符合'], '| 跳过:', stat['跳过'], '| 总待改:', len(changes))

if APPLY:
    print('\n=== 执行改名(实时version+429退避) ===', flush=True)
    ok = fail = skip = 0
    for i, (k, v, cur, tgt) in enumerate(changes):
        try:
            r = rename(k, tgt)
            if r == 'ok': ok += 1
            elif r == 'skip': skip += 1
            else: fail += 1
        except Exception as e:
            fail += 1
            if fail <= 8: print(f'  失败 {k} [{cur[:30]}]: {e}', flush=True)
        if (i+1) % 15 == 0:
            print(f'  进度 {i+1}/{len(changes)} 成功{ok} 跳过{skip} 失败{fail}', flush=True)
        time.sleep(0.4)
    print(f'\n完成：成功 {ok}，已符合跳过 {skip}，失败 {fail}', flush=True)
else:
    print('\n(dry-run。确认后加 apply 执行)')
