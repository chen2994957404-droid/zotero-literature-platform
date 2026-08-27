# -*- coding: utf-8 -*-
"""zotero_client 与 **zotero.org 云端**打交道的那一半：读条目、改标签、传附件。

本文件是全项目唯一出现 `api.zotero.org` 的地方 —— 也因此是唯一需要
机器角色守卫的地方（架构守卫按「谁提到这个域名」来扫）。

为什么单独一个文件（2026-08-27，阶段 3 下半）：
    重构前，写 Zotero 的实现有三份 —— watcher 里的 `set_state_tag`、
    `zotero_upload_attachment.py`、`upload_summaries.py`，
    各自拼 URL、各自拼鉴权头、各自处理版本冲突，加上库房维护那几个共 9 个文件。
    后果不只是重复：**机器角色守卫要在 9 个地方各写一遍**，漏一处闸门就等于不存在。
    收到这里之后，守卫只需要在这个文件里，每个写函数开头一行。

三条约定：
  1. **每个对外的写函数开头都要 `role.require_prod(...)`**（架构守卫会扫）。
  2. **不提供「删除」原语。**踩坑 #28：删除动作会进 Zotero 同步链，
     导致每篇都弹「冲突解决」框。要更新附件，请复用已有条目、只覆盖文件内容。
  3. 版本冲突（`If-Unmodified-Since-Version`）在这里处理，调用方不必关心。
"""
import hashlib
import json
import mimetypes
import os
import urllib.parse
import urllib.request

from core import role


WEB_API = 'https://api.zotero.org'


def _base():
    from adapters.zotero_client import WEB_USER_ID
    return f'{WEB_API}/users/{WEB_USER_ID}'


def _headers():
    from core.config import get_key
    k = get_key('ZOTERO_API_KEY')
    if not k:
        raise RuntimeError('没有 ZOTERO_API_KEY，写不了 Zotero（去控制面板填）')
    return {'Zotero-API-Key': k, 'Zotero-API-Version': '3'}


def _call(path, method='GET', data=None, headers=None, timeout=30, raw=False):
    h = dict(_headers())
    if headers:
        h.update(headers)
    req = urllib.request.Request(_base() + path, data=data, method=method, headers=h)
    resp = urllib.request.urlopen(req, timeout=timeout)
    body = resp.read()
    if raw or not body:
        return body
    return json.loads(body)


def zweb(path, timeout=30):
    """云端只读 API GET。**读不需要机器角色守卫** —— 它不改变任何东西。

    为什么需要它（踩坑 #64）：本地 API 反映的是 Zotero 桌面端**已经同步下来**
    的状态，比刚写上去的东西滞后几分钟。用本地 API 查「我刚传的附件在不在」，
    答案会是「不在」—— 于是又传一份。**自己写上去的东西，要问权威方。**
    """
    return _call(path, timeout=timeout)


def get_item(item_key):
    """取条目（含 version —— 改标签要用它做乐观锁）。读，不需要守卫。"""
    return _call(f'/items/{item_key}')


def replace_tags(item_key, tags, action='更新 Zotero 标签', force=False):
    """把某条目的标签整体换成 `tags`（形如 `[{'tag': '全文精读'}]`）。

    调用方负责决定「该有哪些标签」（那是业务策略，比如状态互斥）；
    这里只负责安全地写进去：带 `If-Unmodified-Since-Version`，
    条目在我们读到之后被别人改过就会失败，而不是悄悄覆盖别人的改动。
    """
    role.require_prod(action, force=force)
    cur = get_item(item_key)
    _call(f'/items/{item_key}', 'PATCH',
          json.dumps({'tags': tags}).encode('utf-8'),
          {'Content-Type': 'application/json',
           'If-Unmodified-Since-Version': str(cur['version'])})
    return True


def upload_attachment(parent_key, filepath, display_name,
                      action='上传附件到 Zotero', force=False):
    """把本地文件作为附件传到某条文献下，返回附件 key。

    Zotero 的四步流程：建条目 → 要上传授权 → 传到授权 URL → 注册完成。
    md5 相同时服务端直接说「已存在」，跳过传输（省流量，也省一次失败机会）。

    ⚠ 要更新已有附件，**别删了重传**（踩坑 #28）——
    用 `find_child_attachment` 找到旧条目复用，只覆盖本地 storage 里的文件。
    """
    role.require_prod(action, force=force)
    fname = os.path.basename(filepath)
    filesize = os.path.getsize(filepath)
    with open(filepath, 'rb') as f:
        content = f.read()
    md5 = hashlib.md5(content).hexdigest()
    mtime = int(os.path.getmtime(filepath) * 1000)
    ctype = mimetypes.guess_type(fname)[0] or 'application/octet-stream'

    # 1. 建 imported_file 附件条目
    item = [{'itemType': 'attachment', 'parentItem': parent_key,
             'linkMode': 'imported_file', 'title': display_name,
             'filename': fname, 'contentType': ctype, 'md5': None, 'mtime': None}]
    r = _call('/items', 'POST', json.dumps(item).encode(),
              {'Content-Type': 'application/json'})
    att_key = r['successful']['0']['key']

    # 2. 要上传授权
    auth = _call(f'/items/{att_key}/file', 'POST',
                 urllib.parse.urlencode({'md5': md5, 'filename': fname,
                                         'filesize': filesize, 'mtime': mtime,
                                         'contentType': ctype}).encode(),
                 {'Content-Type': 'application/x-www-form-urlencoded',
                  'If-None-Match': '*'})
    if auth.get('exists'):
        return att_key                       # 服务端已有同 md5 的文件

    # 3. 传到授权 URL（Zotero 格式：prefix + 文件内容 + suffix）
    body = auth['prefix'].encode('utf-8') + content + auth['suffix'].encode('utf-8')
    urllib.request.urlopen(urllib.request.Request(
        auth['url'], data=body, method='POST',
        headers={'Content-Type': auth['contentType']}), timeout=180)

    # 4. 注册完成（返回 204 空 body）
    _call(f'/items/{att_key}/file', 'POST',
          urllib.parse.urlencode({'upload': auth['uploadKey']}).encode(),
          {'Content-Type': 'application/x-www-form-urlencoded',
           'If-None-Match': '*'}, raw=True)
    return att_key
