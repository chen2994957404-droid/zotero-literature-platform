# -*- coding: utf-8 -*-
"""把本地文件作为 imported_file 附件上传到 Zotero 条目。返回附件key。
Zotero 上传流程：创建attachment条目 → 授权 → 上传 → 注册。
用法(测试): python zotero_upload_attachment.py <parentItemKey> <文件路径> <附件显示名>
"""
import urllib.request, urllib.parse, json, os, hashlib, sys, mimetypes
try:
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
    from modules.config import get_key as _cfg_get
except Exception:
    _cfg_get = lambda n, **kw: _o.environ.get(n, '')

USER_ID = '16078117'
KEY = _cfg_get('ZOTERO_API_KEY')
WEB = 'https://api.zotero.org/users/' + USER_ID
WH = {'Zotero-API-Key': KEY, 'Zotero-API-Version': '3'}

def api(url, method='GET', data=None, headers=None, raw=False):
    h = dict(WH)
    if headers: h.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    resp = urllib.request.urlopen(req, timeout=30)
    return resp.read() if raw else json.loads(resp.read())

def upload_attachment(parent_key, filepath, display_name):
    fname = os.path.basename(filepath)
    filesize = os.path.getsize(filepath)
    with open(filepath, 'rb') as f:
        content = f.read()
    md5 = hashlib.md5(content).hexdigest()
    mtime = int(os.path.getmtime(filepath) * 1000)
    ctype = mimetypes.guess_type(fname)[0] or 'application/octet-stream'

    # 1. 创建 imported_file attachment 条目
    item = [{
        'itemType': 'attachment',
        'parentItem': parent_key,
        'linkMode': 'imported_file',
        'title': display_name,
        'filename': fname,
        'contentType': ctype,
        'md5': None,
        'mtime': None,
    }]
    r = api(WEB + '/items', 'POST', json.dumps(item).encode(),
            {'Content-Type': 'application/json'})
    att_key = r['successful']['0']['key']
    print(f'  创建附件条目 {att_key}')

    # 2. 获取上传授权
    auth_body = urllib.parse.urlencode({
        'md5': md5, 'filename': fname, 'filesize': filesize,
        'mtime': mtime, 'contentType': ctype
    }).encode()
    auth = api(WEB + f'/items/{att_key}/file', 'POST', auth_body,
               {'Content-Type': 'application/x-www-form-urlencoded',
                'If-None-Match': '*'})
    if auth.get('exists'):
        print('  文件已存在(md5相同)，无需上传')
        return att_key

    # 3. 上传文件到授权URL（Zotero格式：prefix + 文件内容 + suffix）
    up = auth['url']
    upload_ct = auth['contentType']
    body = auth['prefix'].encode('utf-8') + content + auth['suffix'].encode('utf-8')
    req = urllib.request.Request(up, data=body, method='POST',
        headers={'Content-Type': upload_ct})
    urllib.request.urlopen(req, timeout=180)
    print('  文件已上传')

    # 4. 注册上传完成（返回204空body，不解析JSON）
    reg_body = urllib.parse.urlencode({'upload': auth['uploadKey']}).encode()
    req = urllib.request.Request(WEB + f'/items/{att_key}/file', data=reg_body, method='POST',
        headers={**WH, 'Content-Type': 'application/x-www-form-urlencoded', 'If-None-Match': '*'})
    urllib.request.urlopen(req, timeout=30)
    print('  上传已注册完成')
    return att_key

if __name__ == '__main__':
    pk, fp, name = sys.argv[1], sys.argv[2], sys.argv[3]
    print(f'上传 {fp} -> 条目 {pk}')
    k = upload_attachment(pk, fp, name)
    print(f'完成，附件key={k}')
