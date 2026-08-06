# -*- coding: utf-8 -*-
"""把 library 里的新版 summary.html 刷进 Zotero 本地 storage，覆盖旧附件文件。

用途：精读被重跑（deepread_batch --force）后，Zotero 里点开的还是旧文件，
本脚本把新版铺进 storage/<附件key>/summary.html，用户点开即最新。

**只改文件内容、不动 Zotero 条目与版本号** —— 因此不会触发同步冲突（踩坑 #18 的教训：
「先删附件再传新的」会把删除动作推进同步链，导致 Zotero 反复弹冲突框）。

用法: python scripts/refresh_summary_file.py KEY1 KEY2 ...
"""
import os, sys, shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, ROOT)
sys.path.insert(0, SCRIPT_DIR)
import zotero_watcher as W


def refresh(key):
    """返回 (是否成功, 说明)。"""
    src = os.path.join(ROOT, 'workflow_data', 'library', key, 'summary.html')
    if not os.path.exists(src):
        return False, '本地无 summary.html'
    att = W.find_existing_summary(key)
    if not att:
        return False, 'Zotero 里没有 summary 附件（需走 watcher 首次上传）'
    d = os.path.join(W.STORAGE_DIR, att)
    os.makedirs(d, exist_ok=True)
    shutil.copy(src, os.path.join(d, 'summary.html'))
    return True, f'-> storage/{att}/summary.html ({round(os.path.getsize(src) / 1024)} KB)'


def main():
    keys = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not keys:
        print(__doc__)
        return
    ok = 0
    for key in keys:
        good, msg = refresh(key)
        ok += good
        print(f'  {key}: {"OK " if good else "跳过 "}{msg}')
    print(f'\n完成：{ok}/{len(keys)} 已刷新')


if __name__ == '__main__':
    main()
