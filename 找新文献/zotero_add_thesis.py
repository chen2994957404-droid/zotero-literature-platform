# -*- coding: utf-8 -*-
"""为毕业论文孤儿附件创建 thesis 条目并挂载附件、归入分类。"""
import os, sys, json, time, urllib.request

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from core import role
from core.cli import flag
from core.config import get_key, need_site
from adapters import zotero_client as zotero

# 本机配置（Zotero 用户ID / 附件目录）统一从 core.config 读，换电脑只改 .env
USER_ID = need_site('ZOTERO_USER_ID')
KEY = get_key('ZOTERO_API_KEY')
STORAGE = need_site('ZOTERO_STORAGE')
THESIS_COLLECTION = '8X73UY35'  # 毕业论文分类

# 手动确认的元数据（从PDF首页读出）
THESES = [
  {'att_key': 'FHQ9NNA2',
   'title': '基于含水动态硬性母材的自修复凝胶的设计与制备研究',
   'author_last': '郭', 'author_first': '华', 'year': '2025', 'univ': '四川大学', 'type': '博士学位论文'},
  {'att_key': 'PXP4AQVC',
   'title': '基于动态化学的糖响应高分子的制备研究',
   'author_last': '阿其他', 'author_first': '', 'year': '2021', 'univ': '四川大学', 'type': '博士学位论文'},
]


def add_thesis(t):
    # 1. 创建 thesis 条目
    creators = []
    if t['author_last']:
        creators = [{'creatorType': 'author', 'lastName': t['author_last'],
                     'firstName': t['author_first']}]
    item = [{
        'itemType': 'thesis',
        'title': t['title'],
        'creators': creators,
        'thesisType': t['type'],
        'university': t['univ'],
        'date': t['year'],
        'collections': [THESIS_COLLECTION],
    }]
    r = zotero.create_items(item, action='新建学位论文条目')
    new_key = r['successful']['0']['key']
    print(f"新建条目 {new_key}: {t['title'][:30]}")
    time.sleep(1)
    # 2. 把孤儿附件挂到新条目下（改 parentItem），再把显示名规范成 Full Text PDF
    att_key = t['att_key']
    zotero.patch_item(att_key, {'parentItem': new_key},
                      action='把附件挂到新建的学位论文条目下', log=print)
    print(f"  附件 {att_key} 已挂到 {new_key}")
    time.sleep(1)
    zotero.patch_item(att_key, {'title': 'Full Text PDF'},
                      action='把附件改名为 Full Text PDF', log=print)
    time.sleep(1)


def main():
    # 机器角色守卫：这件事只允许在运行端（主力机）做，见 docs/两台机器的分工.md
    role.require_prod('往 Zotero 添加学位论文', force=flag('--force'))
    for t in THESES:
        add_thesis(t)
    print('完成')


if __name__ == '__main__':
    main()
