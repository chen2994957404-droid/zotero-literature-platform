# -*- coding: utf-8 -*-
"""把证据库里重复存的文件去掉（一次性运维，2026-09-15）。**不删任何只有一份的东西。**

量过主力机 `data/raw` 39.6 GB，其中两块是纯重复：
    parsed/*_origin.pdf、si_parsed/*_origin.pdf   9.2 GB   MineRU 把输入 PDF 原样抄了一份回来
    _incoming/getpdf/<doi>.pdf                     12 GB    取件区的副本，落地后从没清过
两块都只在「和正本一模一样」时才动：origin.pdf 换成指向正本的硬链接（裁图照旧能找到）；
取件区的副本删掉。大小对不上的一律不碰、报出来。

用法：
    python host/deploy/dedupe_storage.py            # 只看：能省多少
    python host/deploy/dedupe_storage.py --执行     # 真做
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters import pdf_parse
from shared.kernel import catalog, paths
from shared.kernel.cli import flag, wants_help

G = 1e9


def _same(a, b):
    try:
        return os.path.getsize(a) == os.path.getsize(b) and not os.path.samefile(a, b)
    except OSError:
        return False


def origin_copies():
    """→ [(origin.pdf, 正本)]：大小一致、且还不是同一份数据的。"""
    out = []
    for pid in catalog.ids():
        for sub, master in ((paths.parsed_dir(pid), paths.local_pdf(pid)),
                            (paths.si_parsed_dir(pid), paths.find_local_si(pid) or '')):
            if not (master and os.path.isfile(master) and os.path.isdir(sub)):
                continue
            for f in os.listdir(sub):
                if f.endswith('_origin.pdf') and _same(os.path.join(sub, f), master):
                    out.append((os.path.join(sub, f), master))
    return out


def incoming_copies():
    """→ [取件区里已经落地的副本]。按文件名里的 DOI 找回正本，大小一致才算。"""
    d = os.path.join(paths.INCOMING, 'getpdf')
    if not os.path.isdir(d):
        return [], []
    dup, unknown = [], []
    by = catalog.by_doi()
    for f in os.listdir(d):
        p = os.path.join(d, f)
        if not os.path.isfile(p):
            continue
        stem, ext = os.path.splitext(f)
        is_si = stem.endswith('_SI')
        stem = stem[:-3] if is_si else stem
        # safe_name 把 / 换成了 _ ；反查只还原第一个（DOI 里只有一个 /）。别的怪字符还原不了就算 unknown
        doi = stem.replace('_', '/', 1) if stem.startswith('10.') else ''
        pid = by.get(catalog.norm_doi(doi), '') if doi else ''
        master = ''
        if pid:
            master = (paths.find_local_si(pid) or '') if is_si else paths.local_pdf(pid)
        if master and os.path.isfile(master) and os.path.getsize(master) == os.path.getsize(p):
            dup.append(p)
        else:
            unknown.append(p)
    return dup, unknown


def main():
    if wants_help():
        print(__doc__)
        return 0
    do = flag('--执行')
    oc = origin_copies()
    ic, unknown = incoming_copies()
    s1 = sum(os.path.getsize(a) for a, _ in oc) / G
    s2 = sum(os.path.getsize(p) for p in ic) / G
    s3 = sum(os.path.getsize(p) for p in unknown) / G
    print('origin.pdf 与正本重复：%d 个，%.2f GB → 换成硬链接' % (len(oc), s1))
    print('取件区里已落地的副本：%d 个，%.2f GB → 删掉' % (len(ic), s2))
    print('取件区里对不上正本的：%d 个，%.2f GB → 不动（多半是取回来但没落地/落地失败的）' % (len(unknown), s3))
    if not do:
        print('\n以上只是看看。真做：python host/deploy/dedupe_storage.py --执行')
        return 0
    n = 0
    for dup, master in oc:
        n += pdf_parse.link_origin(os.path.dirname(dup), master)
    print('硬链接换了 %d 个' % n)
    m = 0
    for p in ic:
        try:
            os.remove(p); m += 1
        except OSError as e:
            print('  删不掉 %s：%s' % (p, e))
    print('取件区删了 %d 个，共省下约 %.1f GB' % (m, s1 * n / max(1, len(oc)) + s2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
