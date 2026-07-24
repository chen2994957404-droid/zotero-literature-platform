# -*- coding: utf-8 -*-
"""删除清单里的无PDF残留条目（A组+B组）。带429退避。"""
import urllib.request, json, os, time

USER_ID = '16078117'; KEY = '***REMOVED***'
WEB = 'https://api.zotero.org/users/' + USER_ID
WH = {'Zotero-API-Key': KEY, 'Zotero-API-Version': '3'}

j = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'workflow_data', '待删条目清单.json'), encoding='utf-8'))
keys = j['A'] + j['B']
print(f'待删 {len(keys)} 个条目')

ok = fail = 0
for i, k in enumerate(keys):
    for attempt in range(4):
        try:
            # 取最新version
            item = json.loads(urllib.request.urlopen(urllib.request.Request(WEB+'/items/'+k, headers=WH), timeout=15).read())
            v = item['version']
            req = urllib.request.Request(WEB+'/items/'+k, method='DELETE',
                headers={**WH, 'If-Unmodified-Since-Version': str(v)})
            urllib.request.urlopen(req, timeout=15)
            ok += 1
            break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get('Retry-After', 10))); continue
            if e.code == 404:  # 已不存在
                ok += 1; break
            fail += 1
            if fail <= 5: print(f'  失败 {k}: {e}')
            break
        except Exception as e:
            fail += 1; break
    if (i+1) % 15 == 0:
        print(f'  进度 {i+1}/{len(keys)} 成功{ok} 失败{fail}')
    time.sleep(0.3)

print(f'\n完成：删除成功 {ok}，失败 {fail}')
