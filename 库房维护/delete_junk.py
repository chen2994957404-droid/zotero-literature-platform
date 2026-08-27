# -*- coding: utf-8 -*-
"""删除清单里的无PDF残留条目（A组+B组）。带429退避。"""
import urllib.request, urllib.error, json, os, sys, time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from core import paths

from core.config import get_key, need_site

# 本机配置（Zotero 用户ID / 附件目录）统一从 core.config 读，换电脑只改 .env
_UID = need_site('ZOTERO_USER_ID')
_STORAGE = need_site('ZOTERO_STORAGE')
USER_ID = _UID
KEY = get_key('ZOTERO_API_KEY')
WEB = 'https://api.zotero.org/users/' + USER_ID
WH = {'Zotero-API-Key': KEY, 'Zotero-API-Version': '3'}
JUNK_FILE = paths.junk_list('json')


def main():
    j = json.load(open(JUNK_FILE, encoding='utf-8'))
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
            except Exception:
                fail += 1  # 网络/解析等异常统一计失败，不中断整批删除
                break
        if (i+1) % 15 == 0:
            print(f'  进度 {i+1}/{len(keys)} 成功{ok} 失败{fail}')
        time.sleep(0.3)

    print(f'\n完成：删除成功 {ok}，失败 {fail}')


if __name__ == '__main__':
    main()
