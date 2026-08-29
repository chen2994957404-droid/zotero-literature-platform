# -*- coding: utf-8 -*-
"""方向地图 —— 一批高水平论文当种子，看这个领域过去/现在是什么形势。

用法:
    python 找新文献/方向地图.py build <公众号md目录>   # 抓取 + 落库（要联网，几十分钟）
    python 找新文献/方向地图.py cluster                # 聚类（纯本地，可反复调）
    python 找新文献/方向地图.py report                 # 打印地图
    python 找新文献/方向地图.py stats                  # 库里现在有什么

    --min-df N     骨干门槛：被至少 N 篇种子共引才拉元数据（默认 3）
    --min-size N   簇至少多少篇才显示（默认 5）
    --out 文件     report 时同时写文件

第一次用先跑 build，之后 cluster / report 都不再联网。
"""
import os
import sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from core import paths
from core.cli import pos, opt
from pipelines import direction_map as dm


def main():
    action = (pos(0) or 'report').lower()
    if action == 'build':
        seed_dir = pos(1)
        if not seed_dir:
            print('用法: python 找新文献/方向地图.py build <公众号md目录>')
            return 2
        r = dm.build(seed_dir, min_df=int(opt('--min-df', 3)), progress=print)
        print('')
        print('完成：种子 %d 篇 / 参考文献 %d 篇 / 引用边 %d 条 / 骨干元数据 %d 篇'
              % (r['seeds'], r['refs'], r['edges'], r['backbone']))
        print('下一步: python 找新文献/方向地图.py cluster')
    elif action == 'cluster':
        dm.cluster(min_size=int(opt('--min-size', 5)), progress=print)
        print('下一步: python 找新文献/方向地图.py report')
    elif action == 'report':
        out = opt('--out')
        text = dm.report(min_size=int(opt('--min-size', 5)), out=out)
        print(text)
        if out:
            print('')
            print('已写入 ' + out)
    elif action == 'stats':
        s = dm.stats()
        if not s.get('exists'):
            print('还没建库。先跑: python 找新文献/方向地图.py build <公众号md目录>')
            return 1
        print('库: %s' % paths.direction_db())
        print('种子 %d 篇 | 参考文献 %d 篇 | 引用边 %d 条 | 已聚类 %d'
              % (s['seeds'], s['refs'], s['edges'], s['clustered']))
        for k, v in sorted(s['meta'].items()):
            print('  %s: %s' % (k, v[:160]))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
