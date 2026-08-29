# -*- coding: utf-8 -*-
"""bibliometrics · 文献计量纯逻辑（公理：一堆论文 + 它们的引用 → 这个领域长什么样）

**这一环不联网、不知道文件放在哪。** 输入是纯 Python 数据结构，输出也是。
所有需要 OpenAlex 的事情都由 `pipelines/direction_map` 喂进来。

## 为什么这些函数长这样（全部有实测支撑，2026-08-28/29）

三件事是踩出来的，写在这里免得下一个人再踩一遍：

**① 聚类塌成巨块是算法问题，不是数据脏。**
最早用标签传播，754 篇会塌成 67 篇 / 53 篇的巨块，主题纯度只有 0.30。
换成带 resolution 的 Louvain 之后，同样的数据得到 36 个簇、纯度 0.48。
**先确认算法分辨率够，再去怀疑数据** —— 反过来做会白跑好几轮。

**② 通用工具论文会把不相关的论文粘成假簇。**
19 篇论文（有机发光 / 阴离子膜 / 原油分馏）被聚成一簇，唯一共同点是都引了
Multiwfn 和几篇 DFT 方法论文。文献耦合默认「共引 = 同主题」，
但工具是被**所有**主题共引的。

**③ 自动识别工具论文的判据试了三个，全部失败**（别再试这三条）：

| 判据 | 为什么失败 |
|---|---|
| 全球被引 >= 2 万 | 轴选错：关键那篇工具只有 4688 次引用，够不着；而真地基（聚多巴胺 10890 次）差点被误伤 |
| 引用者主题熵高 | 指标饱和：211 篇语料被分成 69 个细粒度主题，任何被 7 篇引的文献熵都是 0.98，结果把 Leibler vitrimer、Gong 聚两性电解质全判成「工具」 |
| 参考文献自身学科不在语料里 | OpenAlex 学科归类噪声太大：大豆蛋白胶归到「营养学」、水凝胶电极归到「神经科学」 |

**结论：小、稳定、众所周知的集合，手工清单胜过任何启发式。**
所以 `DEFAULT_TOOL_PATTERNS` 就是一份显式清单。它**只影响相似度计算**，
被排除的论文照样出现在「地基」清单里 —— 同一份数据，两个用途，两套处理。

⚠ 清单按标题正则匹配，实测会误伤（一篇硫辛酸共聚物论文被 `density functional` 撞上）。
调用方如果有稳定的 id，优先用 `tool_ids=` 显式传，别依赖正则。

对外接口：
    coupling_matrix(refsets, exclude)      → 文献耦合相似度矩阵（IDF 加权）
    louvain(S, resolution, seed)           → 社区发现，返回每个节点的簇号
    modularity(S, labels)                  → 模块度
    best_partition(S, resolutions, ...)    → 扫分辨率，按主题纯度挑最好的一档
    purity(groups, topic_of)               → 主题纯度（客观质量指标）
    tool_refs(titles, patterns)            → 按清单挑出通用工具类参考文献
    half_year(date) / trend(dates)         → 时间趋势分桶
    top_shared(refsets, min_df)            → 地基清单：被最多篇共同引用的参考文献

依赖：numpy（矩阵运算）+ 标准库。
"""
import collections
import math
import random
import re

import numpy as np


# ── 通用工具类参考文献 ────────────────────────────────────────────────
# 这份清单**故意写死**：见模块文档「三个自动判据全部失败」。
# 加新条目的判据：它是不是「任何主题的论文都可能引用的方法/软件」。
DEFAULT_TOOL_PATTERNS = (
    r'multiwfn', r'wavefunction analysis', r'gradient approximation',
    r'ab initio', r'projector augmented', r'self-consistent equations',
    r'dispersion corrected', r'independent gradient model',
    r'interaction region indicator', r'gromacs', r'lammps',
    r'electronic structure and molecular dynamics software',
    r'iterative schemes for ab initio',
)


def tool_refs(titles, patterns=DEFAULT_TOOL_PATTERNS):
    """titles: {ref_id: 标题} → 判为通用工具的 ref_id 集合。

    ⚠ 正则匹配标题会误伤（实测撞过一篇硫辛酸论文）。有稳定 id 时优先手工列 id。
    """
    pat = re.compile('(' + '|'.join(patterns) + ')', re.I)
    return set(k for k, t in titles.items() if t and pat.search(t))


# ── 文献耦合 ──────────────────────────────────────────────────────────
def coupling_matrix(refsets, exclude=(), keys=None):
    """按「共享参考文献」算论文两两相似度（bibliographic coupling）。

    refsets: {论文id: 它引用的 ref_id 集合}
    exclude: 不参与计算的 ref_id（通用工具）—— 见模块文档 ②

    公式：共享参考文献的 **IDF 之和** / sqrt(|A|·|B|)。
    用 IDF 而不是简单计数，是因为「两篇都引了某篇冷门文献」比
    「都引了某篇人人都引的综述」信息量大得多。
    返回 (keys, S)：keys 是行列顺序，S 是对称矩阵。
    """
    keys = list(keys) if keys is not None else sorted(refsets)
    n = len(keys)
    exclude = set(exclude)
    sets = [set(refsets.get(k) or ()) - exclude for k in keys]

    df = collections.Counter()
    for s in sets:
        df.update(s)

    S = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        a = sets[i]
        if not a:
            continue
        for j in range(i + 1, n):
            b = sets[j]
            if not b:
                continue
            shared = a & b
            if not shared:
                continue
            w = sum(math.log(n / df[r]) for r in shared) / math.sqrt(len(a) * len(b))
            S[i, j] = S[j, i] = w
    return keys, S


# ── 社区发现 ──────────────────────────────────────────────────────────
def louvain(S, resolution=1.0, seed=0, max_passes=50):
    """Louvain 局部移动阶段，返回 labels（长度 = 节点数）。

    只做第一阶段（不做图收缩）：本项目的图是几百到几千个节点、稠密加权，
    第一阶段已经能给出稳定结果，收缩阶段带来的收益不值那份复杂度。

    resolution 越大簇越细。**这是最重要的旋钮** —— 见模块文档 ①。
    """
    n = S.shape[0]
    m2 = float(S.sum())
    if n == 0 or m2 == 0:
        return list(range(n))
    rnd = random.Random(seed)
    deg = S.sum(1)
    com = list(range(n))
    ctot = deg.copy()
    order = list(range(n))
    for _ in range(max_passes):
        rnd.shuffle(order)
        moved = 0
        for i in order:
            ci = com[i]
            ctot[ci] -= deg[i]
            links = collections.defaultdict(float)
            for j in np.nonzero(S[i])[0]:
                if j != i:
                    links[com[j]] += S[i, j]
            best, gain = ci, links.get(ci, 0.0) - resolution * ctot[ci] * deg[i] / m2
            for c, w in links.items():
                g = w - resolution * ctot[c] * deg[i] / m2
                if g > gain:
                    best, gain = c, g
            com[i] = best
            ctot[best] += deg[i]
            if best != ci:
                moved += 1
        if not moved:
            break
    return com


def modularity(S, labels):
    """加权模块度。注意：**它不是质量的唯一标准** ——

    实测里分辨率调高会让模块度下降、主题纯度上升，而后者才是我们要的
    （簇更细、更贴主题）。所以 best_partition 按纯度挑，不按模块度挑。
    """
    m = float(S.sum()) / 2.0
    if m == 0:
        return 0.0
    deg = S.sum(1)
    labels = list(labels)
    q = 0.0
    for c in set(labels):
        mask = np.array([l == c for l in labels])
        q += S[np.ix_(mask, mask)].sum() / (2 * m) - (deg[mask].sum() / (2 * m)) ** 2
    return float(q)


def groups_of(keys, labels, min_size=1):
    """labels → [[成员key, ...], ...]，按簇大小降序。"""
    g = collections.defaultdict(list)
    for k, c in zip(keys, labels):
        g[c].append(k)
    return [m for m in sorted(g.values(), key=len, reverse=True) if len(m) >= min_size]


def purity(groups, topic_of, min_size=4):
    """主题纯度：簇内共享主导主题的成员占比，按簇大小加权。

    这是**客观质量指标**：主题标签来自外部（OpenAlex），与我们的聚类完全独立，
    所以它能真正判断「簇是不是有意义」，而模块度只能判断「图切得整不整齐」。
    """
    total, acc = 0, 0.0
    for mem in groups:
        if len(mem) < min_size:
            continue
        c = collections.Counter(topic_of(k) for k in mem)
        if not c:
            continue
        acc += c.most_common(1)[0][1]
        total += len(mem)
    return acc / total if total else 0.0


def best_partition(S, keys, topic_of, resolutions=(1.5, 2.0, 2.5, 3.0),
                   tries=10, min_size=5):
    """扫分辨率，按主题纯度挑最好的一档。返回 (labels, 报告列表)。

    报告列表每项 = (resolution, 模块度, 簇数, 覆盖篇数, 纯度)，便于把过程打出来 ——
    「为什么选这一档」应该是看得见的，而不是藏在代码里的一个魔数。
    """
    report, best = [], None
    for res in resolutions:
        bl, bq = None, -1.0
        for s in range(tries):
            l = louvain(S, res, seed=s)
            q = modularity(S, l)
            if q > bq:
                bl, bq = l, q
        gs = groups_of(keys, bl, min_size=1)
        big = [m for m in gs if len(m) >= min_size]
        p = purity(gs, topic_of)
        report.append((res, bq, len(big), sum(len(m) for m in big), p))
        if best is None or p > best[0]:
            best = (p, bl)
    return best[1], report


# ── 时间趋势 ──────────────────────────────────────────────────────────
def half_year(date):
    """'2026-05-13' → '2026H1'。认不出来返回 None。"""
    if not date or len(date) < 7:
        return None
    try:
        y, m = int(date[:4]), int(date[5:7])
    except ValueError:
        return None
    return '%dH%d' % (y, 1 if m <= 6 else 2)


def trend(dates, periods=None):
    """一组日期 → {半年: 篇数}，外加按 periods 顺序排好的列表。

    ⚠ 调用方要自己记得：**最后一个半年可能不满半年**（比如 2026H2 只有 7、8 两月），
    直接拿它跟前面比会得出「在下降」的错觉。方向判断请用 direction() 并看清期数。
    """
    c = collections.Counter(x for x in (half_year(d) for d in dates) if x)
    if periods is None:
        periods = sorted(c)
    return c, [c.get(p, 0) for p in periods]


def direction(counts, split=None):
    """趋势箭头。counts 是按时间排好的列表，split 前后两段比总量。

    返回 '↑↑'（后段 >= 前段两倍）/ '↑' / '=' / '↓'。
    """
    if not counts:
        return '='
    split = split if split is not None else len(counts) // 2
    a, b = sum(counts[:split]), sum(counts[split:])
    if b >= 2 * max(a, 1):
        return '↑↑'
    return '↑' if b > a else ('↓' if b < a else '=')


# ── 地基清单 ──────────────────────────────────────────────────────────
def shared_counts(refsets):
    """{ref_id: 被多少篇论文共同引用}。这是**不需要任何模型的重要性排序** ——

    实测：754 篇种子引出 39218 篇唯一文献，其中 90% 只被一篇引用（各自的背景引用），
    真正的骨架只有几百篇。期刊档次筛不出来的老奠基作（Leibler 2011 vitrimer、
    Gong 2013 聚两性电解质），靠这个指标一下就顶出来了。
    """
    c = collections.Counter()
    for s in refsets.values():
        c.update(s or ())
    return c


def top_shared(refsets, min_df=3, limit=None):
    """地基清单：[(ref_id, 被几篇共引)]，降序。"""
    c = shared_counts(refsets)
    out = [(r, n) for r, n in c.most_common() if n >= min_df]
    return out[:limit] if limit else out
