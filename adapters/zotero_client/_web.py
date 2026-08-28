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
import time
import urllib.error
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


def _with_retry(do, tries=4, log=None):
    """替「会变的外部世界」兜底：限流退避 + 版本冲突重取。

    两种错值得重试，别的一律往上抛：
      · **429 限流**：按 Retry-After 等一等（Zotero 会明说等多久）
      · **412 版本冲突**：我们读到版本号之后、写之前，条目被别人（多半是
        Zotero 桌面同步）改了。重取版本再来一次即可。

    这段逻辑原来在 4 个脚本里各抄了一遍，而**最该有它的 watcher 改标签反而没有** ——
    于是精读做完了、标签没换成，用户只看到「怎么还是待处理」。
    收进适配层之后，谁写 Zotero 谁自动拥有它。
    """
    last = None
    for attempt in range(tries):
        try:
            return do()
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:
                wait = int(e.headers.get('Retry-After', 10) or 10)
                if log:
                    log(f'  Zotero 限流，{wait}s 后重试（{attempt + 1}/{tries}）')
                time.sleep(wait)
                continue
            if e.code == 412:                 # 版本冲突：重取版本再来
                time.sleep(1)
                continue
            raise
    raise last


def patch_item(item_key, data, action='修改 Zotero 条目', force=False, log=None):
    """改条目的某些字段（只传要改的键）。带乐观锁，别人改过就失败而不是覆盖。

    这是所有「改 Zotero 条目」的唯一实现：打标签、改附件名、改元数据都走它。
    重构前这段 `GET 版本 → PATCH + If-Unmodified-Since-Version` 在 6 个脚本里
    各抄了一遍，**每抄一遍就多一处可能漏掉机器角色守卫的地方**。
    """
    role.require_prod(action, force=force)

    def once():
        cur = _call(f'/items/{item_key}')      # 每次重试都重取版本
        return _call(f'/items/{item_key}', 'PATCH',
                     json.dumps(data, ensure_ascii=False).encode('utf-8'),
                     {'Content-Type': 'application/json',
                      'If-Unmodified-Since-Version': str(cur['version'])}, raw=True)
    _with_retry(once, log=log)
    return True


def create_items(items, action='在 Zotero 里新建条目', force=False):
    """新建条目（传 list）。返回 Zotero 的响应（含 successful/failed 明细）。"""
    role.require_prod(action, force=force)
    return _call('/items', 'POST',
                 json.dumps(items, ensure_ascii=False).encode('utf-8'),
                 {'Content-Type': 'application/json'})


def delete_item(item_key, action='删除 Zotero 条目', force=False, log=None):
    """删除条目。**只用于用户明确要求删除的东西**（如清理垃圾条目）。

    ⚠ 绝不要拿它来「更新产物」——「先删旧附件再传新的」正是踩坑 #28 的根因：
    删除动作会进 Zotero 同步链，于是每篇都弹一次「冲突解决」框。
    更新附件请用 `find_child_attachment` 复用条目、只覆盖文件内容。
    """
    role.require_prod(action, force=force)

    def once():
        cur = _call(f'/items/{item_key}')
        return _call(f'/items/{item_key}', 'DELETE', None,
                     {'If-Unmodified-Since-Version': str(cur['version'])}, raw=True)
    try:
        _with_retry(once, log=log)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return True            # 已经不在了 = 目的达成，不算失败
        raise
    return True


def replace_tags(item_key, tags, action='更新 Zotero 标签', force=False, log=None):
    """把某条目的标签整体换成 `tags`（形如 `[{'tag': '全文精读'}]`）。

    调用方负责决定「该有哪些标签」（那是业务策略，比如状态互斥）；
    这里只负责安全地写进去：带 `If-Unmodified-Since-Version`，
    条目在我们读到之后被别人改过就会失败，而不是悄悄覆盖别人的改动。
    """
    return patch_item(item_key, {'tags': tags}, action=action, force=force, log=log)


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


def check_key(timeout=15):
    """这把 Zotero API key 有效吗、属于哪个账号？返回 (ok, 说明, 详情dict)。

    **顺带回答「我连的是不是我以为的那个库」** —— 两台机器 + 一个测试账号之后，
    「key 属于账号 A、配置里写着账号 B」是个真实存在的错法，
    症状是所有写操作 403，而看起来像「密钥坏了」。
    """
    import urllib.error as _ue
    try:
        d = _call('/keys/current')
    except _ue.HTTPError as e:
        if e.code in (403, 404):
            return False, '密钥无效或已撤销（HTTP %d）' % e.code, {}
        return False, f'查不了：HTTP {e.code}', {}
    except Exception as e:
        return None, f'连不上 zotero.org：{type(e).__name__}', {}
    from core.config import web_user_id
    uid = str(d.get('userID', ''))
    want = str(web_user_id() or '')
    acc = d.get('access', {}).get('user', {})
    can_write = bool(acc.get('write') or acc.get('library'))
    if want and uid != want:
        return False, (f'密钥属于账号 {uid}（{d.get("username")}），'
                       f'但本机配的是 {want} —— 写操作会全部 403'), d
    if not can_write:
        return False, f'密钥没有写权限（账号 {uid}），回写会失败', d
    return True, f'有效，账号 {uid}（{d.get("username")}），有写权限', d


def _call_get(path, timeout=30):     # 兼容别处可能的调用
    return _call(path, timeout=timeout)
