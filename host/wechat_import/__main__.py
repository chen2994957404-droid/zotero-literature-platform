# -*- coding: utf-8 -*-
"""把公众号推送导进 Zotero，并把推文本身当正文精读装上。

用法:
    python -m host.wechat_import --dry-run              # 先看会导哪些（什么都不写）
    python -m host.wechat_import --limit 5              # 最近 5 篇：建条目 + 装精读
    python -m host.wechat_import --limit 5 --with-pdf   # 连正文 PDF 与 SI 一起取到本地
    python -m host.wechat_import --limit 5 --with-pdf --upload-summary  # 精读也传进 Zotero
    python -m host.wechat_import --limit 5 --with-pdf --upload   # 连 PDF 与 SI 一起传
    python -m host.wechat_import --file <某篇.md>       # 只导指定的一篇

目录默认取配置里的「公众号推送下载目录」，也可以用 `--dir` 指定。

**会写 Zotero**（建条目、打标签），所以要么在主力机上跑，要么在配了测试账号的
编程端跑。`--dry-run` 不写任何东西，只告诉你会发生什么。

**附件默认不传**：正文 PDF、SI、精读都先落在本地 `data/` 里 ——
Zotero 免费存储只有 300 MB，够不了几十篇。
`--upload-summary` 只传精读（小，而且是你天天看的那份，传了在 Zotero 里点开就能读）；
`--upload` 连正文 PDF 与 SI 一起传（很占配额，实测有 34.9 MB 的综述）。

`--with-pdf` 需要那台机器上开着「取全文用的浏览器」（见 tools/getpdf）。
不开也能跑，只是先没有正文 PDF，以后随时能补。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
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

    role.require_prod('把公众号精读导进 Zotero（建条目、传附件、打标签）',
                      force=flag('--force'))
    res = wi.import_many(files, purpose=opt('--purpose') or '建库',
                         with_pdf=flag('--with-pdf'),
                         upload=('all' if flag('--upload')
                                 else 'summary' if flag('--upload-summary') else False),
                         force=flag('--force'))
    ok = [r for r in res if r['key']]
    print('\n完成：%d/%d 篇进库（新建 %d，本来就有 %d）'
          % (len(ok), len(res),
             sum(1 for r in res if r['action'] == 'created'),
             sum(1 for r in res if r['action'] == 'exists')))
    print('正文PDF %d 篇、SI %d 篇已落到本地 data/ 里%s'
          % (sum(1 for r in res if r.get('pdf')), sum(1 for r in res if r.get('si')),
             '' if flag('--upload') else '（原件没传 Zotero —— 要传加 --upload）'))
    for r in res:
        if not r['key']:
            print('  未处理 %s —— %s' % (r['file'][:40], r['note']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
