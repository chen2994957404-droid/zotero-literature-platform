# -*- coding: utf-8 -*-
"""Zotero 附件统一命名：正文→Full Text PDF、SI→SI、网页快照→Snapshot。
数据源用全库JSON(快)，改名用Web API。
用法: python zotero_rename.py <全库json路径> [apply]
  不带apply=只分析(dry-run)；带apply=真正改
"""
import urllib.request, urllib.error, json, re, os, sys, time
from collections import Counter

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import role
from shared.kernel.cli import pos, flag
from shared.kernel.config import get_key, need_site
from shared.adapters import zotero_client as zotero

# 本机配置（Zotero 用户ID / 附件目录）统一从 shared.kernel.config 读，换电脑只改 .env
_UID = need_site('ZOTERO_USER_ID')
_STORAGE = need_site('ZOTERO_STORAGE')
USER_ID = _UID
WEB_KEY = get_key('ZOTERO_API_KEY')

JSON_PATH = pos(0)
APPLY = pos(1) == 'apply'

SUPP = re.compile(r'suppmat|supp[_\-\.]|supporting|supplement|[_\-]si[_\-\.]|_si_?\d|si[_\-]?\d{3}|appendix|支持信息|支持性信息|补充材料|补充信息', re.I)


def classify(d):
    ct = d.get('contentType', '')
    fn = d.get('filename') or ''
    title = d.get('title') or ''
    name = fn + ' ' + title
    lm = d.get('linkMode', '')
    if ct == 'text/html' or 'snapshot' in lm.lower():
        return 'Snapshot'
    if SUPP.search(name) or title.strip() == 'SI':
        return 'SI'
    if ct == 'application/pdf':
        return 'Full Text PDF'
    return None


def get_current(att_key):
    """实时取附件当前 version 和 title（避免用旧 version 冲突）。"""
    d = zotero.get_item(att_key)
    return d['version'], (d['data'].get('title') or d['data'].get('filename') or '')


def rename(att_key, new_title, forced=False):
    """改附件显示名。重取版本、限流退避、版本冲突重试都在适配层里。"""
    _ver, cur = get_current(att_key)
    if cur == new_title:
        return 'skip'
    try:
        zotero.patch_item(att_key, {'title': new_title},
                          action=f'把附件改名为「{new_title}」', force=forced, log=print)
        return 'ok'
    except Exception as e:
        print(f'  [改名失败] {att_key}: {e}')
        return 'fail'


def main():
    # 机器角色守卫：这件事只允许在运行端（主力机）做，见 docs/两台机器的分工.md
    role.require_prod('附件改名（写回 Zotero）', force=flag('--force'))
    items = json.load(open(JSON_PATH, encoding='utf-8'))
    atts = [x for x in items if x['data'].get('itemType') == 'attachment' and x['data'].get('parentItem')]

    stat = Counter()
    changes = []
    for a in atts:
        d = a['data']
        tgt = classify(d)
        cur = d.get('title') or d.get('filename') or ''
        if tgt is None:
            stat['跳过'] += 1; continue
        if cur == tgt:
            stat['已符合'] += 1; continue
        stat[tgt] += 1
        changes.append((a['key'], a['version'], cur, tgt))

    print('子附件总数:', len(atts))
    print('待改 Full Text PDF:', stat['Full Text PDF'], '| SI:', stat['SI'], '| Snapshot:', stat['Snapshot'])
    print('已符合:', stat['已符合'], '| 跳过:', stat['跳过'], '| 总待改:', len(changes))

    if APPLY:
        print('\n=== 执行改名(实时version+429退避) ===', flush=True)
        ok = fail = skip = 0
        for i, (k, v, cur, tgt) in enumerate(changes):
            try:
                r = rename(k, tgt)
                if r == 'ok': ok += 1
                elif r == 'skip': skip += 1
                else: fail += 1
            except Exception as e:
                fail += 1  # 单个附件改名失败已打印原因，不中断整批
                if fail <= 8: print(f'  失败 {k} [{cur[:30]}]: {e}', flush=True)
            if (i+1) % 15 == 0:
                print(f'  进度 {i+1}/{len(changes)} 成功{ok} 跳过{skip} 失败{fail}', flush=True)
            time.sleep(0.4)
        print(f'\n完成：成功 {ok}，已符合跳过 {skip}，失败 {fail}', flush=True)
    else:
        print('\n(dry-run。确认后加 apply 执行)')


if __name__ == '__main__':
    main()
