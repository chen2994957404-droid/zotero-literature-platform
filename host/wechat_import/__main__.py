# -*- coding: utf-8 -*-
"""把公众号推送收进证据库，并把推文本身当正文精读装上。（2026-10-13 起不再写 Zotero。）

用法:
    python -m host.wechat_import --dry-run              # 先看会导哪些（什么都不写）
    python -m host.wechat_import --limit 5              # 最近 5 篇：收进证据库 + 装精读
    python -m host.wechat_import --limit 5 --with-pdf   # 连正文 PDF 与 SI 一起取到本地
    python -m host.wechat_import --file <某篇.md>       # 只导指定的一篇
    python -m host.wechat_import --金标 --limit 50        # 配精读金标：推文当范文存起来，原件进证据库
    python -m host.wechat_import --金标 --只用手上有的      # 同上但不向出版商取，先看手上能配多少
    python -m host.wechat_import --重写范文                # 解析规则变了，只重写已配对的 reference.md
    python -m host.wechat_import --金标 --limit 300 --两路  # 两路并发取件（按出版商错开；不许更多）

目录默认取配置里的「公众号推送下载目录」，也可以用 `--dir` 指定。

**会写证据库**（主力机上跑）。`--dry-run` 不写任何东西，只告诉你会发生什么。

`--with-pdf` 需要那台机器上开着「取全文用的浏览器」（见 tools/getpdf）。
不开也能跑，只是先没有正文 PDF，以后随时能补。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.kernel import role
from shared.kernel.cli import flag, opt, wants_help
from shared.kernel.config import get_site

from host import wechat_import as wi


def _targets():
    """要处理哪些 md。目录不传就用配置里的「公众号推送下载目录」。"""
    f = opt('--file')
    if f:
        return [f]
    d = opt('--dir') or get_site('WECHAT_DIR')
    if not d or not os.path.isdir(d):
        return []
    return wi.list_dir(d)          # 从新到旧，--limit 才是「最近几篇」


def main():
    if wants_help():
        print(__doc__)
        return 0
    files = _targets()
    if not files:
        print('没找到 .md —— 传 --dir，或在控制面板里填「公众号推送下载目录」')
        return 1
    limit = int(opt('--limit') or 0)
    if limit:
        files = files[:limit]

    if flag('--dry-run'):
        print('【试跑】不写任何东西。共 %d 篇：' % len(files))
        for p in files:
            a = wi.parse_md(p)
            n_img = sum(1 for b in a['blocks'] if b['kind'] == 'img')
            n_txt = sum(len(b.get('text', '')) for b in a['blocks'])
            print('  %-9s %d字 %d图  %s' % (a['doi'] or '(没DOI)', n_txt, n_img,
                                            a['title'][:40]))
        return 0

    if flag('--重写范文'):
        from host.wechat_import import golden
        golden.rewrite_references(files)
        return 0

    if flag('--金标') or flag('--golden'):
        # 不装精读：推文只当**标尺**存成 reference.md（见 golden.py）。
        from host.wechat_import import golden
        res = golden.build(files, allow_fetch=not flag('--只用手上有的'),
                           workers=2 if flag('--两路') else 1)
        print()
        print(golden.summarize(res))
        return 0

    # 这里**故意不接 --force**：那个开关的意思是「产物重做一遍」，不该顺带关掉机器角色的保护。
    role.require_prod('把公众号精读收进证据库（取原件、装精读）')
    res = wi.import_many(files, with_pdf=flag('--with-pdf'), force=flag('--force'))
    ok = [r for r in res if r['key']]
    print('\n完成：%d/%d 篇进库（新建 %d，本来就有 %d）'
          % (len(ok), len(res),
             sum(1 for r in res if r['action'] == 'created'),
             sum(1 for r in res if r['action'] == 'exists')))
    print('正文PDF %d 篇、SI %d 篇已落到本地 data/ 里'
          % (sum(1 for r in res if r.get('pdf')), sum(1 for r in res if r.get('si'))))
    for r in res:
        if not r['key']:
            print('  未处理 %s —— %s' % (r['file'][:40], r['note']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
