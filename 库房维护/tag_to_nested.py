# -*- coding: utf-8 -*-
"""把维度标签从 dim:value 格式转成 Zotero Style 嵌套格式 dim/value。
支持中断续跑（已转的会跳过）。用法: python tag_to_nested.py [apply]
不带apply=预览；带apply=真改。
"""
import urllib.request, urllib.error, json, os, sys, time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import role
from shared.kernel.cli import pos, flag
from shared.kernel.config import get_key, need_site, get_site
from shared.adapters import zotero_client as zotero

# 本机配置（Zotero 用户ID / 附件目录）统一从 shared.kernel.config 读，换电脑只改 .env
_UID = need_site('ZOTERO_USER_ID')
_STORAGE = need_site('ZOTERO_STORAGE')
USER_ID = _UID
KEY = get_key('ZOTERO_API_KEY')
LOCAL = get_site('ZOTERO_API_HOST') + '/api/users/' + USER_ID
LH = {'Zotero-Allowed-Request': 'true'}
APPLY = pos(0) == 'apply'

DIMS = ('topic', 'material', 'mechanism', 'method', 'type')


def lget(p):
    return json.loads(urllib.request.urlopen(urllib.request.Request(LOCAL+p, headers=LH), timeout=20).read())


def main():
    # 机器角色守卫：这件事只允许在运行端（主力机）做，见 docs/两台机器的分工.md
    forced = flag('--force')
    role.require_prod('标签改造（写回 Zotero）', force=forced)
    # 取所有顶层文献
    tops = []; s = 0
    while True:
        d = lget(f'/items/top?limit=100&start={s}')
        if not d: break
        tops += d; s += 100
        if len(d) < 100: break

    # 找有 dim: 格式标签、还没转成 dim/ 的
    todo = []
    for x in tops:
        tags = x['data'].get('tags', [])
        need = False
        newtags = []
        for t in tags:
            tag = t.get('tag', '')
            # dim:value -> dim/value
            converted = False
            for dim in DIMS:
                if tag.startswith(dim + ':'):
                    newtags.append({'tag': dim + '/' + tag[len(dim)+1:]})
                    converted = True; need = True
                    break
            if not converted:
                newtags.append(t)
        if need:
            todo.append((x['key'], newtags))

    print(f'需要转换的文献: {len(todo)} 篇')
    if not APPLY:
        # 预览前3篇
        for k, tags in todo[:3]:
            print(k, '->', [t['tag'] for t in tags if '/' in t['tag']][:5])
        print('\n(预览。加 apply 执行)')
        sys.exit()

    ok = fail = 0
    for i, (key, newtags) in enumerate(todo):
        try:
            zotero.replace_tags(key, newtags, action='标签改成嵌套写法', force=forced, log=print)
            ok += 1
        except Exception as e:
            print(f'  [写回失败] {key}: {e}')
            fail += 1      # 单篇失败不中断整批
        if (i+1) % 20 == 0:
            print(f'  {i+1}/{len(todo)} 成功{ok} 失败{fail}')
        time.sleep(0.3)
    print(f'\n完成：成功 {ok}，失败 {fail}')


if __name__ == '__main__':
    main()
