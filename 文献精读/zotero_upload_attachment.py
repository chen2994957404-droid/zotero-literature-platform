# -*- coding: utf-8 -*-
"""把本地文件作为 imported_file 附件上传到 Zotero 条目。返回附件key。
Zotero 上传流程：创建attachment条目 → 授权 → 上传 → 注册。
用法(测试): python zotero_upload_attachment.py <parentItemKey> <文件路径> <附件显示名>
"""
import os, sys, re, json, hashlib, mimetypes, urllib.parse, urllib.request

# 【标准开头】项目根加入 import 路径 + 强制 UTF-8 输出（详见 docs/代码规范_标准脚本模板.md）
_ROOT = os.path.dirname(os.path.abspath(__file__))
while True:
    if os.path.isdir(os.path.join(_ROOT, 'modules')):
        break                      # 项目根特征：modules/ 目录只在根存在
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        break                      # 到盘符根，兜底
    _ROOT = parent
sys.path.insert(0, _ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from modules.cli import pos
from modules.config import get_key, need_site

# 本机配置（Zotero 用户ID / 附件目录）统一从 modules.config 读，换电脑只改 .env
USER_ID = need_site('ZOTERO_USER_ID')
_STORAGE = need_site('ZOTERO_STORAGE')   # 校验必填项存在（附件目录上传后落盘用）
KEY = get_key('ZOTERO_API_KEY')
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


def main():
    pk, fp, name = pos(0), pos(1), pos(2)
    if not (pk and fp and name):
        print(__doc__)
        sys.exit(1)
    print(f'上传 {fp} -> 条目 {pk}')
    k = upload_attachment(pk, fp, name)
    print(f'完成，附件key={k}')


if __name__ == '__main__':
    main()
