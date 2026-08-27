# -*- coding: utf-8 -*-
"""批量回写精读到 Zotero：对给定 key 列表，把 library/<key>/summary.html
作为 'summary' 附件上传（删旧→传新→写本地storage），并加「已精读」标签。

复用 zotero_upload_attachment.upload_attachment。用于 deepread_batch 之后补回写。
用法: python upload_summaries.py --file keys.txt  |  python upload_summaries.py KEY1 KEY2
"""
import os, sys, json, shutil, urllib.request

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from core import paths, role
from core.paths import ROOT as _ROOT

from core.cli import opt, positionals, flag
from core.config import get_key, need_site

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
from adapters import zotero_client as zotero

ROOT = _ROOT
LIBRARY = paths.LIBRARY
# 本机配置（Zotero 用户ID / 附件目录）统一从 core.config 读，换电脑只改 .env
# 写 zotero.org 必须用真实数字 id（本地 API 的 0 在这里写不进去）
from core.config import web_user_id
USER_ID = web_user_id() or need_site('ZOTERO_USER_ID')
STORAGE_DIR = need_site('ZOTERO_STORAGE')
WEB_API_KEY = get_key('ZOTERO_API_KEY')
DONE_TAG = '已精读'


def refresh_summary(key, html):
    """把某篇的精读回写成 Zotero 附件：**有就复用条目、只换文件内容**。

    ⚠ 这里原来是「先删旧附件、再传新的」—— 那正是踩坑 #28 的根因：
    删除动作会进 Zotero 同步链，于是每篇都弹一次「冲突解决」框。
    watcher 早已改成复用，这个批量脚本却一直留着旧写法（同一个 bug 的两份实现，
    修了一份忘了另一份 —— 这也是把写操作收进适配层的直接理由）。
    """
    att_key = zotero.find_child_attachment(key, 'summary')
    if not att_key:
        att_key = zotero.upload_attachment(key, html, 'summary')
    d = os.path.join(STORAGE_DIR, att_key)
    os.makedirs(d, exist_ok=True)
    shutil.copy(html, os.path.join(d, 'summary.html'))    # 本地点开即最新
    return att_key


def add_done_tag(key):
    """给文献加「已精读」标签（保留原有标签）。"""
    try:
        item = zotero.get_item(key)
        tags = item['data'].get('tags', [])
        if any(t.get('tag') == DONE_TAG for t in tags):
            return
        tags.append({'tag': DONE_TAG})
        zotero.replace_tags(key, tags, action='加「已精读」标签')
    except Exception as e:
        print(f'    (加标签失败: {e})')


def do_one(key):
    html = paths.summary(key)
    if not os.path.exists(html):
        print(f'  [跳过] 无 summary.html')
        return False
    try:
        refresh_summary(key, html)
    except Exception as e:
        print(f'  [上传失败] {e}')
        return False
    add_done_tag(key)
    print(f'  [已上传] summary + 标签「已精读」')
    return True


def main():
    # 机器角色守卫：这件事只允许在运行端（主力机）做，见 docs/两台机器的分工.md
    role.require_prod('批量回写精读附件', force=flag('--force'))
    fp = opt('--file')
    if fp:
        keys = [l.strip() for l in open(fp, encoding='utf-8') if l.strip()]
    else:
        keys = positionals()
    print(f'回写 {len(keys)} 篇精读到 Zotero\n')
    ok = 0
    for i, k in enumerate(keys, 1):
        print(f'[{i}/{len(keys)}] {k}')
        if do_one(k): ok += 1
    print(f'\n完成：成功 {ok}/{len(keys)}')


if __name__ == '__main__':
    main()
