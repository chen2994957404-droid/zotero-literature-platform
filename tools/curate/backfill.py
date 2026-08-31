# -*- coding: utf-8 -*-
"""给 library 里缺 meta.json 的文献补齐元数据（从 Zotero 读）。

为什么要有这一步：数据契约要求每篇都有 `meta.json`（标题/DOI/日期）。
缺了它，对比表里那篇会变成一行没名字的记录，问答也说不出答案来自哪篇。

**只写平台自己的产物目录，不碰 Zotero**（所以不需要机器角色守卫）。
用法: python -m tools.curate.backfill
"""
import io
import json
import os
import sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters import zotero_client as zotero
from shared.kernel import paths


def item_data(key):
    """取一条 Zotero 条目的 data 字段。走适配层，红线 #5。"""
    return zotero.zget(f'/users/{zotero.USER_ID}/items/{key}')['data']


def backfill_one(key):
    """补一篇。返回 'done' / 'skip'（已有）/ 'none'（不是文献目录）。失败抛异常。"""
    d = os.path.join(paths.CURATED, key)
    if not os.path.isdir(d):
        return 'none'
    if os.path.exists(paths.meta(key)):
        return 'skip'
    data = item_data(key)
    io.open(paths.meta(key), 'w', encoding='utf-8').write(json.dumps(
        {'key': key, 'title': data.get('title', ''), 'DOI': data.get('DOI', ''),
         'date': data.get('date', ''), 'model': 'unknown(backfilled)',
         'time': 'backfilled'}, ensure_ascii=False, indent=1))
    return 'done'


def main():
    done = skip = fail = 0
    for key in sorted(os.listdir(paths.CURATED)):
        try:
            r = backfill_one(key)
        except Exception as e:
            print(f'失败 {key}: {e}')   # 单篇失败已打印原因，继续下一篇
            fail += 1
            continue
        if r == 'done':
            print(f'补齐 {key}')
            done += 1
        elif r == 'skip':
            skip += 1
    print(f'\n完成：补齐 {done}，已有跳过 {skip}，失败 {fail}')


if __name__ == '__main__':
    main()
