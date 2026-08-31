# -*- coding: utf-8 -*-
"""bibliometrics 自测：验证聚类能把「本来就该分开的」分开，且不被工具论文粘住。
用法: python shared/domain/bibliometrics/selftest.py

重点测那个**真实踩过的坑**：三组毫不相关的论文，因为都引了同一批 DFT 工具，
会被文献耦合粘成一个假簇。排除工具后必须分开。
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.domain import bibliometrics as bib

ok = True


def check(name, cond, detail=''):
    global ok
    print(('  [OK]   ' if cond else '  [FAIL] ') + name + (('  ' + detail) if detail else ''))
    if not cond:
        ok = False


# ── 构造：复现真实的假簇 ──────────────────────────────────────────
# ⚠ 这里的构造有个**反直觉的前提**（第一版测试就栽在这）：
# 相似度用 IDF 加权，log(n/df) 对「被所有论文都引的文献」**直接归零**，
# 所以「全员都引同一批工具」根本粘不住 —— 它自己就被中和掉了。
#
# 真实的假簇成因是：工具被**一部分**论文共引（实测 Multiwfn 是 754 篇里的 14 篇，
# IDF 权重很高）。所以这里必须有一组不引工具的论文把 df 压下来。
#
#   a/b/c 三组各 5 篇：各自 2 篇专属参考文献 + 共用 8 篇 DFT 工具
#   d 组 15 篇：只有自己的参考文献，不碰工具
# 于是工具的 df=15/30，权重足以压过组内那 2 篇专属文献 → a/b/c 被粘成一坨。
TOOLS = {'T_multiwfn', 'T_pbe', 'T_gromacs', 'T_lammps', 'T_paw',
         'T_ab_initio', 'T_igm', 'T_dispersion'}
TOOL_TITLES = {
    'T_multiwfn': 'Multiwfn: A multifunctional wavefunction analyzer',
    'T_pbe': 'Generalized Gradient Approximation Made Simple',
    'T_gromacs': 'GROMACS: High performance molecular simulations',
    'T_lammps': 'LAMMPS - a flexible simulation tool',
    'T_paw': 'Projector augmented-wave method',
    'T_ab_initio': 'Iterative schemes for ab initio total-energy calculations',
    'T_igm': 'Independent gradient model based on Hirshfeld partition',
    'T_dispersion': 'Effect of the damping function in dispersion corrected DFT',
    'R_a1': 'Tough adhesives for diverse wet surfaces'}
refsets = {}
for tag in 'abc':
    for i in range(5):
        refsets['P_%s%d' % (tag, i)] = (
            set('R_%s%d' % (tag, j) for j in range(2)) | TOOLS
            | {'R_%s%d_uniq' % (tag, i)})
for i in range(15):
    refsets['P_d%d' % i] = set('R_d%d' % j for j in range(3)) | {'R_d%d_uniq' % i}

print('== 1. 工具清单识别 ==')
found = bib.tool_refs(TOOL_TITLES)
check('认出 8 篇工具论文', found == TOOLS, str(len(found)))
check('没把真论文误判成工具', 'R_a1' not in found)


def _abc_clusters(labels, keys):
    """a/b/c 三组的成员落在几个不同的簇里。"""
    m = dict(zip(keys, labels))
    return len(set(m[k] for k in keys if k[2] in 'abc'))


print('== 2. 工具论文会在不相关主题之间造出相似度（假簇的成因）==')
# 直接测**机制**而不是测 Louvain 的判断：后者还受分辨率、度分布影响，
# 用它当断言会得到一个「时灵时不灵」的测试。这里断言的是确定性的矩阵事实。
keys, S1 = bib.coupling_matrix(refsets)
ix = {k: i for i, k in enumerate(keys)}
cross = S1[ix['P_a0'], ix['P_b0']]        # a 组和 b 组毫无关系，只共享工具
within = S1[ix['P_a0'], ix['P_a1']]
check('工具在 a/b 之间造出了相似度', cross > 0, 'S(a0,b0)=%.3f' % cross)
check('这个假相似度不算小', cross > 0.5 * within,
      'cross=%.3f vs within=%.3f' % (cross, within))

keys, S1x = bib.coupling_matrix(refsets, exclude=TOOLS)
check('排除工具后 a/b 之间相似度归零',
      S1x[ix['P_a0'], ix['P_b0']] == 0, 'S=%.3f' % S1x[ix['P_a0'], ix['P_b0']])
check('组内相似度依然存在', S1x[ix['P_a0'], ix['P_a1']] > 0,
      'S=%.3f' % S1x[ix['P_a0'], ix['P_a1']])

print('== 3. 排除工具后分回三组 ==')
keys, S2 = bib.coupling_matrix(refsets, exclude=TOOLS)
lab2 = bib.louvain(S2, resolution=1.0, seed=0)
g2 = bib.groups_of(keys, lab2, min_size=1)
check('a/b/c 分回三个簇', _abc_clusters(lab2, keys) == 3,
      '落在 %d 个簇' % _abc_clusters(lab2, keys))
check('连同 d 组共四个簇', len(g2) == 4, '簇数=%d' % len(g2))
pure = all(len(set(k[2] for k in mem)) == 1 for mem in g2)
check('每个簇内主题一致', pure)

print('== 4. 模块度与纯度 ==')
q = bib.modularity(S2, lab2)
check('模块度为正', q > 0, 'Q=%.3f' % q)
p = bib.purity(g2, lambda k: k[2], min_size=1)
check('主题纯度 = 1.0', abs(p - 1.0) < 1e-6, 'purity=%.2f' % p)

print('== 5. best_partition 会报出每一档 ==')
lab3, rep = bib.best_partition(S2, keys, lambda k: k[2],
                               resolutions=(1.0, 2.0), tries=3, min_size=2)
check('报告有两档', len(rep) == 2, str([r[0] for r in rep]))
check('报告每项 5 个字段', all(len(r) == 5 for r in rep))

print('== 6. 时间趋势 ==')
check('半年分桶 H1', bib.half_year('2026-05-13') == '2026H1')
check('半年分桶 H2', bib.half_year('2026-07-01') == '2026H2')
check('认不出的返回 None', bib.half_year('') is None)
_, series = bib.trend(['2025-02-01', '2025-03-01', '2026-01-01', '2026-02-01',
                       '2026-03-01', '2026-04-01'], ['2025H1', '2026H1'])
check('分桶计数正确', series == [2, 4], str(series))
check('翻倍判为 ↑↑', bib.direction([1, 1, 5, 5]) == '↑↑')
check('下降判为 ↓', bib.direction([5, 5, 1, 1]) == '↓')

print('== 7. 地基清单 ==')
top = bib.top_shared(refsets, min_df=5)
check('组内共享文献进得了地基', any(r.startswith('R_a') for r, _ in top))
check('只被一篇引的不进地基', not any(r.endswith('_uniq') for r, _ in top))

print('')
print('全部通过' if ok else '有失败项')
sys.exit(0 if ok else 1)
