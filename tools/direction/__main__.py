# -*- coding: utf-8 -*-
"""方向地图 —— 一条窄带里，谁做了什么、用了什么方法、实现了什么性能、用在哪。

用法（--band 必填，因为一条窄带一个库）:
    python -m tools.direction bands                        # 现有窄带
    python -m tools.direction seeds   --band impact         # 三路取种子（联网）
    python -m tools.direction wechat  --band X --dir <目录>  # 从公众号 md 取种子
    python -m tools.direction build   --band impact         # 建图（联网，十几分钟）
    python -m tools.direction cluster --band impact         # 聚类（纯本地，可反复调）
    python -m tools.direction report  --band impact --out 地图.txt
    python -m tools.direction stats   --band impact

    --min-df N     骨干门槛：被至少 N 篇种子共引才拉元数据（默认 3）
    --min-size N   簇至少多少篇才显示（默认 5）

第一次用一条新窄带：先写 band.json（见 tools/direction/CLAUDE.md），
再 seeds → build → cluster → report。之后 cluster / report 都不再联网。
"""
import os
import sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import paths
from shared.kernel.cli import pos, opt
from tools import direction as dm


def _band():
    b = opt('--band')
    if not b:
        print('缺 --band。现有窄带：%s' % (', '.join(paths.direction_bands()) or '（还没有）'))
        print('用法见文件顶部注释。')
        raise SystemExit(2)
    return b


def main():
    action = (pos(0) or 'stats').lower()

    if action == 'bands':
        bands = paths.direction_bands()
        if not bands:
            print('还没有任何窄带。')
            return 0
        for b in bands:
            s = dm.stats(b)
            print('%-18s 种子池 %-6s 种子 %-6s 参考文献 %-7s 边 %-8s 已聚类 %s'
                  % (b, s.get('seed_pool', 0), s.get('seeds', 0), s.get('refs', 0),
                     s.get('edges', 0), s.get('clustered', 0)))
        return 0

    band = _band()

    if action == 'seeds':
        r = dm.collect_seeds(band, progress=print)
        print('')
        print('下一步: python -m tools.direction build --band %s' % band)
        return 0 if r['total'] else 1

    if action == 'wechat':
        d = opt('--dir') or pos(1)
        if not d:
            print('用法: python -m tools.direction wechat --band X --dir <公众号md目录>')
            return 2
        dm.seeds_from_wechat(band, d, progress=print)
        return 0

    if action == 'build':
        r = dm.build(band, min_df=int(opt('--min-df', 3)), progress=print)
        print('')
        print('完成：种子 %d 篇 / 参考文献 %d 篇 / 引用边 %d 条 / 骨干元数据 %d 篇'
              % (r['seeds'], r['refs'], r['edges'], r['backbone']))
        print('下一步: python -m tools.direction cluster --band %s' % band)
        return 0

    if action == 'cluster':
        dm.cluster(band, min_size=int(opt('--min-size', 5)), progress=print)
        print('下一步: python -m tools.direction report --band %s' % band)
        return 0

    if action == 'report':
        out = opt('--out')
        text = dm.report(band, min_size=int(opt('--min-size', 5)), out=out)
        print(text)
        if out:
            print('')
            print('已写入 ' + out)
        return 0

    if action == 'stats':
        s = dm.stats(band)
        if not s.get('exists'):
            print('窄带「%s」还没建库。先跑 seeds → build。' % band)
            return 1
        print('库: %s' % paths.direction_db(band))
        print('种子池 %d（%s）' % (s['seed_pool'],
              ' · '.join('%s %d' % kv for kv in sorted(s['by_source'].items())) or '—'))
        print('种子 %d 篇 | 参考文献 %d 篇 | 引用边 %d 条 | 已聚类 %d'
              % (s['seeds'], s['refs'], s['edges'], s['clustered']))
        for k, v in sorted(s['meta'].items()):
            print('  %s: %s' % (k, v[:150]))
        return 0

    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
