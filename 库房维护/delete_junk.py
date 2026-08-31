# -*- coding: utf-8 -*-
"""删除清单里的无PDF残留条目（A组+B组）。带429退避。"""
import urllib.request, urllib.error, json, os, sys, time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from shared.kernel import paths, role
from shared.kernel.cli import flag

from shared.kernel.config import get_key, need_site
from shared.adapters import zotero_client as zotero

# 本机配置（Zotero 用户ID / 附件目录）统一从 shared.kernel.config 读，换电脑只改 .env
_UID = need_site('ZOTERO_USER_ID')
_STORAGE = need_site('ZOTERO_STORAGE')
USER_ID = _UID
KEY = get_key('ZOTERO_API_KEY')
JUNK_FILE = paths.junk_list('json')


def main():
    # 机器角色守卫：这件事只允许在运行端（主力机）做，见 docs/两台机器的分工.md
    forced = flag('--force')
    role.require_prod('删除 Zotero 条目', force=forced)
    j = json.load(open(JUNK_FILE, encoding='utf-8'))
    keys = j['A'] + j['B']
    print(f'待删 {len(keys)} 个条目')

    ok = fail = 0
    for i, k in enumerate(keys):
        # 删除走适配层：取版本、限流退避、「本来就不在了算成功」都在那里。
        # 适配层刻意把删除单独做成一个原语并写明边界 ——
        # **它只用于用户明确要删的条目，绝不用于「更新产物」**（踩坑 #28）。
        try:
            zotero.delete_item(k, action='删除垃圾条目', force=forced, log=print)
            ok += 1
        except Exception as e:
            fail += 1
            if fail <= 5:
                print(f'  失败 {k}: {e}')
        if (i+1) % 15 == 0:
            print(f'  进度 {i+1}/{len(keys)} 成功{ok} 失败{fail}')
        time.sleep(0.3)

    print(f'\n完成：删除成功 {ok}，失败 {fail}')


if __name__ == '__main__':
    main()
