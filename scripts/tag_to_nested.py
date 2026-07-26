# -*- coding: utf-8 -*-
"""把维度标签从 dim:value 格式转成 Zotero Style 嵌套格式 dim/value。
支持中断续跑（已转的会跳过）。用法: python tag_to_nested.py [apply]
不带apply=预览；带apply=真改。
"""
import urllib.request, json, sys, time
try:
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
    from modules.config import get_key as _cfg_get
except Exception:
    _cfg_get = lambda n, **kw: _o.environ.get(n, '')

USER_ID = '16078117'; KEY = _cfg_get('ZOTERO_API_KEY')
LOCAL = 'http://localhost:23119/api/users/' + USER_ID
WEB = 'https://api.zotero.org/users/' + USER_ID
LH = {'Zotero-Allowed-Request': 'true'}
WH = {'Zotero-API-Key': KEY, 'Zotero-API-Version': '3'}
APPLY = len(sys.argv) > 1 and sys.argv[1] == 'apply'

DIMS = ('topic', 'material', 'mechanism', 'method', 'type')

def lget(p):
    return json.loads(urllib.request.urlopen(urllib.request.Request(LOCAL+p, headers=LH), timeout=20).read())

# 取所有顶层文献
tops = []; s = 0
while True:
    d = lget(f'/items/top?limit=100&start={s}')
    if not d: break
    tops += d; s += 100
    if len(d) < 100: break

# 找有 dim: 格式标签、还没转成 dim/ 的
todo = []
for x in tops:
    tags = x['data'].get('tags', [])
    need = False
    newtags = []
    for t in tags:
        tag = t.get('tag', '')
        # dim:value -> dim/value
        converted = False
        for dim in DIMS:
            if tag.startswith(dim + ':'):
                newtags.append({'tag': dim + '/' + tag[len(dim)+1:]})
                converted = True; need = True
                break
        if not converted:
            newtags.append(t)
    if need:
        todo.append((x['key'], newtags))

print(f'需要转换的文献: {len(todo)} 篇')
if not APPLY:
    # 预览前3篇
    for k, tags in todo[:3]:
        print(k, '->', [t['tag'] for t in tags if '/' in t['tag']][:5])
    print('\n(预览。加 apply 执行)')
    sys.exit()

ok = fail = 0
for i, (key, newtags) in enumerate(todo):
    for attempt in range(4):
        try:
            ver = lget(f'/items/{key}')['version']
            patch = json.dumps({'tags': newtags}).encode()
            req = urllib.request.Request(WEB+f'/items/{key}', data=patch, method='PATCH',
                headers={**WH, 'If-Unmodified-Since-Version': str(ver), 'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=20)
            ok += 1; break
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(int(e.headers.get('Retry-After', 10))); continue
            if e.code == 412: time.sleep(1); continue
            fail += 1; break
        except Exception:
            fail += 1; break
    if (i+1) % 20 == 0:
        print(f'  {i+1}/{len(todo)} 成功{ok} 失败{fail}')
    time.sleep(0.3)
print(f'\n完成：成功 {ok}，失败 {fail}')
