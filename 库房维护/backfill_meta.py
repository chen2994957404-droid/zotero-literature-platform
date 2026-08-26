# -*- coding: utf-8 -*-
"""给 library 里缺 meta.json 的文献补齐元数据（从 Zotero 本地API读）。
保证所有文献结构一致，符合数据契约。
用法: python backfill_meta.py
"""
import os, sys, json, urllib.request

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

from modules.config import need_site, get_site

# 本机配置（Zotero 用户ID / 附件目录）统一从 modules.config 读，换电脑只改 .env
_UID = need_site('ZOTERO_USER_ID')
_STORAGE = need_site('ZOTERO_STORAGE')
USER_ID = _UID
LOCAL = get_site('ZOTERO_API_HOST') + '/api/users/' + USER_ID
LH = {'Zotero-Allowed-Request': 'true'}
LIBRARY = os.path.join(_ROOT, 'workflow_data', 'library')


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
