# -*- coding: utf-8 -*-
"""「导入公众号精读」的向导 —— 给不懂编程的人用，双击 bat 就走到这里。

它替人回答三个问题：目录在哪、这次导几篇、先看看会导哪些。
**先试跑给人看，人点头才真导** —— 这条线会写 Zotero，不能一声不吭就动库。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import role
from shared.kernel.config import get_site
from shared.kernel.cli import flag

from host import wechat_import as wi


def _ask(prompt, default=''):
    try:
        s = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return ''
    return s or default


def _pick_dir():
    d = get_site('WECHAT_DIR')
    if d and os.path.isdir(d):
        return d
    if d:
        print('配置里写的目录不存在：%s' % d)
    print('还没设置公众号下载目录。')
    print('可以现在粘一个进来，也可以打开控制面板填「公众号推送下载目录」。')
    d = _ask('目录路径（直接回车放弃）：').strip('"')
    return d if d and os.path.isdir(d) else ''


def main():
    print('=' * 56)
    print(' 把公众号推送导进 Zotero（推文直接当正文精读）')
    print('=' * 56)
    d = _pick_dir()
    if not d:
        print('没有目录可读，退出。')
        return 1

    files = wi.list_dir(d)          # 从新到旧（日期在正文里，不在文件名里）
    print('\n这个文件夹里有 %d 篇推送。' % len(files))
    if not files:
        return 1

    n = _ask('这次导几篇？（默认 5 篇，从最新的往回数；输入 all 表示全部）：', '5')
    if n.lower() == 'all':
        pick = files
    else:
        try:
            pick = files[:max(1, int(n))]
        except ValueError:
            print('看不懂「%s」，按 5 篇算。' % n)
            pick = files[:5]

    print('\n先试跑一遍，看看会导哪些（这一步什么都不写）：\n')
    todo = []
    for p in pick:
        a = wi.parse_md(p)
        n_img = sum(1 for b in a['blocks'] if b['kind'] == 'img')
        n_txt = sum(len(b.get('text', '')) for b in a['blocks'])
        if a['doi']:
            todo.append(p)
            print('  ✓ %s  %d字 %d图  %s' % (a['doi'], n_txt, n_img, a['title'][:34]))
        else:
            print('  – 跳过（没有 DOI，多半不是论文推送）：%s' % a['title'][:34])

    if not todo:
        print('\n没有一篇带 DOI，不用导。')
        return 0
    print('\n要导 %d 篇。它们会：进 Zotero（合集 LLM导入/建库用）、'
          '带上推文当正文精读、打标签「正文精读·公众号」。' % len(todo))
    if _ask('确认开始吗？(y/N) ').lower() not in ('y', 'yes', '是'):
        print('好，什么都没做。')
        return 0

    role.require_prod('把公众号精读导进 Zotero（建条目、传附件、打标签）',
                      force=flag('--force'))
    res = wi.import_many(todo, with_pdf=flag('--with-pdf'))
    ok = [r for r in res if r['key']]
    print('\n完成：%d/%d 篇进库（新建 %d，本来就有 %d）'
          % (len(ok), len(res),
             sum(1 for r in res if r['action'] == 'created'),
             sum(1 for r in res if r['action'] == 'exists')))
    for r in res:
        if not r['key']:
            print('  没成：%s —— %s' % (r['file'][:40], r['note']))
    print('\n正文 PDF 没跟着下 —— 想要的话在控制面板里跑「取全文」，'
          '或者让 Zotero 自己「查找可用 PDF」。' if not flag('--with-pdf') else '')
    return 0


if __name__ == '__main__':
    sys.exit(main())
