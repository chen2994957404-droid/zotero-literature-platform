# -*- coding: utf-8 -*-
"""给 library 里缺 meta.json 的文献补齐元数据（从 Zotero 本地API读）。
保证所有文献结构一致，符合数据契约。
用法: python backfill_meta.py
"""
import os, sys, json, urllib.request

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from core import paths

from core.config import need_site, get_site

# 本机配置（Zotero 用户ID / 附件目录）统一从 core.config 读，换电脑只改 .env
_UID = need_site('ZOTERO_USER_ID')
_STORAGE = need_site('ZOTERO_STORAGE')
USER_ID = _UID
LOCAL = get_site('ZOTERO_API_HOST') + '/api/users/' + USER_ID
LH = {'Zotero-Allowed-Request': 'true'}
LIBRARY = paths.LIBRARY


def zget_item(key):
    req = urllib.request.Request(f'{LOCAL}/items/{key}', headers=LH)
    return json.loads(urllib.request.urlopen(req, timeout=15).read())['data']


def main():
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
            print(f'失败 {key}: {e}')   # 单篇失败已打印原因，继续下一篇
            fail += 1

    print(f'\n完成：补齐 {done}，已有跳过 {skip}，失败 {fail}')


if __name__ == '__main__':
    main()
