# -*- coding: utf-8 -*-
"""library 自测：不碰 Zotero、不联网，验渲染与「最近 N 天」的判断。

查库那几个函数本身没有可离线测的东西（它们只是转发给适配层），
真正会写错的是**渲染**和**日期过滤**，所以这里只测这两块。
真实库连通验证走 `python -m tools.library stats`（要 Zotero 开着）。
"""
import io, os, sys
from datetime import datetime, timedelta, timezone
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from tools import library

ITEMS = [
    {'key': 'AAAA0001', 'itemType': 'journalArticle', 'title': 'A boron elastomer',
     'creators': ['Li M', 'Wang H'], 'date': '2024', 'publicationTitle': 'Macromolecules',
     'DOI': '10.1000/x', 'url': '', 'tags': ['已精读', 'dim:boron']},
    {'key': 'BBBB0002', 'itemType': 'journalArticle', 'title': '', 'creators': [],
     'date': '', 'publicationTitle': '', 'DOI': '', 'url': '', 'tags': []},
]
COLS = [{'key': 'C1', 'name': '弹性体', 'parent': None},
        {'key': 'C2', 'name': '自修复', 'parent': 'C1'},
        {'key': 'C3', 'name': '硼', 'parent': None}]


def main():
    ok = total = 0

    def check(name, cond, detail=''):
        nonlocal ok, total
        total += 1
        if cond:
            print(f'  [PASS] {name}'); ok += 1
        else:
            print(f'  [FAIL] {name}' + (f' —— {detail}' if detail else ''))

    t = library.render_items(ITEMS, total=7)
    check('渲染条目：带总数抬头', '共 7 条，显示前 2 条' in t, t[:60])
    check('渲染条目：无标题不崩', '(无标题)' in t)
    check('渲染条目：带 key', 'key：AAAA0001' in t)
    check('渲染条目：空列表有话说', library.render_items([]) == '（无结果）')

    d = library.render_item({'item': ITEMS[0], 'attachments':
                             [{'key': 'ATT1', 'title': 'Full Text PDF',
                               'contentType': 'application/pdf'}],
                             'notes_count': 2, 'pdf_path': r'C:\z\a.pdf',
                             'pdf_attachment_key': 'ATT1'})
    check('渲染单篇：标题在第一行', d.splitlines()[0] == '# A boron elastomer', d[:40])
    check('渲染单篇：列出附件', 'Full Text PDF' in d)
    check('渲染单篇：有 PDF 时给路径', r'C:\z\a.pdf' in d)
    nod = library.render_item({'item': ITEMS[1], 'attachments': [], 'notes_count': 0,
                               'pdf_path': None, 'pdf_attachment_key': None})
    check('渲染单篇：没 PDF 说清楚', '未找到' in nod)

    tree = library.render_collections(COLS)
    check('渲染合集：子集缩进', '  - 自修复 (C2)' in tree, tree)
    check('渲染合集：顶层不缩进', '\n- 弹性体 (C1)' in tree)

    tg = library.render_tags([{'tag': 'a', 'numItems': 3}])
    check('渲染标签：带篇数', '- a（3 篇）' in tg, tg)
    check('渲染标签：空也不崩', library.render_tags([]) == '（没有标签）')

    now = datetime.now(timezone.utc)
    check('最近 N 天：昨天算在内',
          library._within((now - timedelta(days=1)).isoformat().replace('+00:00', 'Z'), 7))
    check('最近 N 天：一年前不算',
          not library._within((now - timedelta(days=365)).isoformat().replace('+00:00', 'Z'), 7))
    check('最近 N 天：日期解析不了就保守保留', library._within('不是日期', 7))

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
