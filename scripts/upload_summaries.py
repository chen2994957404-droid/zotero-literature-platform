# -*- coding: utf-8 -*-
"""批量回写精读到 Zotero：对给定 key 列表，把 library/<key>/summary.html
作为 'summary' 附件上传（删旧→传新→写本地storage），并加「已精读」标签。

复用 zotero_upload_attachment.upload_attachment。用于 deepread_batch 之后补回写。
用法: python upload_summaries.py --file keys.txt  |  python upload_summaries.py KEY1 KEY2
"""
import os, sys, json, shutil, urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)
from zotero_upload_attachment import upload_attachment
try:
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
    from modules.config import get_key as _cfg_get
except Exception:
    _cfg_get = lambda n, **kw: _o.environ.get(n, '')

LIBRARY = os.path.join(ROOT, 'workflow_data', 'library')
USER_ID = '16078117'
STORAGE_DIR = r'D:\03_Software\Zetero\Zotero\storage'
WEB_API_KEY = _cfg_get('ZOTERO_API_KEY')
DONE_TAG = '已精读'
BASE = f'https://api.zotero.org/users/{USER_ID}'
WH = {'Zotero-API-Key': WEB_API_KEY, 'Zotero-API-Version': '3'}

def delete_old_summary(key):
    try:
        req = urllib.request.Request(BASE + f'/items/{key}/children', headers=WH)
        for c in json.loads(urllib.request.urlopen(req, timeout=15).read()):
            if c['data'].get('itemType') == 'attachment' and c['data'].get('title') == 'summary':
                dreq = urllib.request.Request(BASE + f'/items/{c["key"]}', method='DELETE',
                    headers={**WH, 'If-Unmodified-Since-Version': str(c['version'])})
                urllib.request.urlopen(dreq, timeout=15)
    except Exception as e:
        print(f'    (删旧summary跳过: {e})')

def add_done_tag(key):
    """给文献加「已精读」标签（保留原有标签）。"""
    try:
        req = urllib.request.Request(BASE + f'/items/{key}', headers=WH)
        item = json.loads(urllib.request.urlopen(req, timeout=15).read())
        tags = item['data'].get('tags', [])
        if any(t.get('tag') == DONE_TAG for t in tags):
            return
        tags.append({'tag': DONE_TAG})
        body = json.dumps({'tags': tags}).encode()
        preq = urllib.request.Request(BASE + f'/items/{key}', data=body, method='PATCH',
            headers={**WH, 'Content-Type': 'application/json',
                     'If-Unmodified-Since-Version': str(item['version'])})
        urllib.request.urlopen(preq, timeout=15)
    except Exception as e:
        print(f'    (加标签失败: {e})')

def do_one(key):
    html = os.path.join(LIBRARY, key, 'summary.html')
    if not os.path.exists(html):
        print(f'  [跳过] 无 summary.html'); return False
    delete_old_summary(key)
    att_key = upload_attachment(key, html, 'summary')
    if att_key:
        d = os.path.join(STORAGE_DIR, att_key); os.makedirs(d, exist_ok=True)
        shutil.copy(html, os.path.join(d, 'summary.html'))
        add_done_tag(key)
        print(f'  [已上传] summary + 标签「已精读」'); return True
    print(f'  [上传失败]'); return False

def main():
    if '--file' in sys.argv:
        keys = [l.strip() for l in open(sys.argv[sys.argv.index('--file')+1], encoding='utf-8') if l.strip()]
    else:
        keys = [a for a in sys.argv[1:] if not a.startswith('--')]
    print(f'回写 {len(keys)} 篇精读到 Zotero\n')
    ok = 0
    for i, k in enumerate(keys, 1):
        print(f'[{i}/{len(keys)}] {k}')
        if do_one(k): ok += 1
    print(f'\n完成：成功 {ok}/{len(keys)}')

if __name__ == '__main__':
    main()
