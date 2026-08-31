# -*- coding: utf-8 -*-
"""文献查询库的命令行入口 —— **逻辑在 `tools/paperdb`**，本文件只解析参数。

把 `structured/*.json` 建成一个能查的 SQLite 库，回答此前答不了的问题：
「含硼、拉伸强度 > 10 MPa 的体系都有哪些」「哪些篇有合成条件但没有性能数值」。

用法:
  python -m tools.paperdb --rebuild        # 从 structured/*.json 重建（秒级、不花钱）
  python -m tools.paperdb --stats          # 各档次 × 各字段有值率（数据有多准）
  python -m tools.paperdb --props tensile  # 抽到过哪些性能、各多少条、范围多大
  python -m tools.paperdb --find boron --prop tensile --min 10
  python -m tools.paperdb --field synthesis_conditions  # 这个字段真有值的篇
  python -m tools.paperdb --sql "SELECT tier, COUNT(*) n FROM papers GROUP BY tier"

**库是索引不是真相**：真相是 `structured/<key>.json`。库随时可删可重建，
所以本入口只读不写（`--sql` 只接受 SELECT / WITH）。
"""
import sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel.cli import flag, opt, wants_help
from tools import paperdb


def _print_rows(rows, cols=None, width=42):
    if not rows:
        print('（没有匹配的记录）')
        return
    cols = cols or list(rows[0].keys())
    print(' | '.join(cols))
    print('-' * 60)
    for r in rows:
        print(' | '.join(str(r.get(c, ''))[:width].replace('\n', ' ') for c in cols))
    print(f'\n共 {len(rows)} 条')


def main():
    if wants_help():
        print(__doc__ or main.__doc__)
        return 0
    if flag('--rebuild'):
        paperdb.rebuild()
        return

    if flag('--stats'):
        cov = paperdb.stats()
        tiers = [t for t in ('精+SI', '精层', '粗层') if t in cov]
        print('字段有值率（空格是「本来没有」还是「没抽到」，看这里）\n')
        print('字段'.ljust(24) + ''.join(f'{t}({cov[t]["n"]}篇)'.rjust(14) for t in tiers))
        for f in (cov[tiers[0]]['rate'] if tiers else {}):
            print(f.ljust(24) + ''.join(
                f'{round(cov[t]["rate"][f] * 100)}%'.rjust(14) for t in tiers))
        return

    if opt('--props') is not None or flag('--props'):
        _print_rows(paperdb.props(opt('--props')))
        return

    sql = opt('--sql')
    if sql:
        _print_rows(paperdb.query(sql))
        return

    mn, mx = opt('--min'), opt('--max')
    rows = paperdb.find(text=opt('--find'), tier=opt('--tier'), field=opt('--field'),
                         prop=opt('--prop'), unit=opt('--unit'),
                         min_value=float(mn) if mn else None,
                         max_value=float(mx) if mx else None,
                         limit=int(opt('--limit', 50)))
    _print_rows(rows, ['key', 'tier', 'title', 'material_system',
                       'dynamic_bond_type', 'key_properties'])


if __name__ == '__main__':
    main()
