# -*- coding: utf-8 -*-
"""给 library 里缺 meta.json 的文献补齐元数据（从 Zotero 本地API读）。
保证所有文献结构一致，符合数据契约。
用法: python backfill_meta.py
"""
import os, json, urllib.request

USER_ID = '16078117'
LOCAL = 'http://localhost:23119/api/users/' + USER_ID
LH = {'Zotero-Allowed-Request': 'true'}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBRARY = os.path.join(ROOT, 'workflow_data', 'library')

def zget_item(key):
    req = urllib.request.Request(f'{LOCAL}/items/{key}', headers=LH)
    return json.loads(urllib.request.urlopen(req, timeout=15).read())['data']

done = skip = fail = 0
for key in os.listdir(LIBRARY):
    d = os.path.join(LIBRARY, key)
    if not os.path.isdir(d):
        continue
    meta_path = os.path.join(d, 'meta.json')
    if os.path.exists(meta_path):
        skip += 1
        continue
    try:
        data = zget_item(key)
        meta = {
            'key': key,
            'title': data.get('title', ''),
            'DOI': data.get('DOI', ''),
            'date': data.get('date', ''),
            'model': 'unknown(backfilled)',
            'time': 'backfilled',
        }
        json.dump(meta, open(meta_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'补齐 {key}: {meta["title"][:40]}')
        done += 1
    except Exception as e:
        print(f'失败 {key}: {e}')
        fail += 1

print(f'\n完成：补齐 {done}，已有跳过 {skip}，失败 {fail}')
