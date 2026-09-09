# -*- coding: utf-8 -*-
"""libmatch · 「这篇跟我的库是什么关系」——**纯判断，不联网、不知道文件在哪**。

## 解决的真实问题

找文献时最先要回答的从来不是「有哪些文献」，而是**「这篇我是不是早就有了」**。
这个判断以前只长在 `tools/discover/match.py` 里，于是任何别的工具想问同一个问题，
就只能把 `tools/discover` import 进来 —— 那是硬规则 2 明令禁止的（工具不许互相 import）。

2026-09-09 拆「找文献」时下沉到这里：`tools/discover`（系统性铺一遍）与
`tools/litsearch`（对抗式检索取原料）**都要问这个问题**，满足下沉规则的「≥2 个使用者」。

## 为什么住在 domain 而不是 adapters

「库里有哪些标题和 DOI」是**取数**，那一步在 `shared/adapters/zotero_client.library_index()`；
「拿到这两个集合之后怎么判断像不像」是**算法**，就是本模块。
所以本模块**只接收调用方传进来的集合**，自己一次网都不联、一个路径都不认识。
换掉 Zotero 换不到这里，改判重口径才会改到这里。

## 公开函数

| 函数 | 干什么 |
|---|---|
| `norm_title(t)` | 标题归一：去标点、空白、大小写。精确层比对用 |
| `cosine(a, b)` | 余弦相似度。维度不一致或全零返回 0，不抛异常 |
| `char_overlap(a, b)` | 粗略字符级重合度，做「标题也像吗」的二次确认 |
| `mark_have(papers, have_titles, have_dois)` | 就地标注每篇的 `in_library`，返回命中数 |

## 两个阈值也在这里

`DUP_SIM` / `STRONG_SIM` 是**判重与相关性的口径**，属于「我们自己的想法」，
所以跟算法放在一起，而不是散落在各调用方。
"""
import re

# 语义相似度高于此值 + 标题也像 → 基本可断定是同一篇（换了写法）
DUP_SIM = 0.92
# 语义相似度高于此值 → 与我的方向强相关，值得优先看
STRONG_SIM = 0.75


def norm_title(t):
    """标题归一：去标点、空白、大小写。用于精确层比对。"""
    return re.sub(r'[^a-z0-9]', '', (t or '').lower())


def cosine(a, b):
    """余弦相似度。向量维度不一致或全零时返回 0，不抛异常。"""
    try:
        s = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(y * y for y in b) ** 0.5
        return s / (na * nb) if na and nb else 0.0
    except Exception:
        return 0.0


def char_overlap(a, b):
    """粗略字符级重合度，用于「标题也像吗」的二次确认。"""
    if not a or not b:
        return 0.0
    sa, sb = set(a[i:i + 4] for i in range(len(a) - 3)), set(b[i:i + 4] for i in range(len(b) - 3))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def mark_have(papers, have_titles, have_dois):
    """就地给每篇标上 `in_library`（True/False），返回命中的篇数。

    `have_titles` / `have_dois` 由调用方传进来 —— 通常来自
    `shared.adapters.zotero_client.library_index()`。**本模块不去取它们**，
    因为取数要联网，那是 adapters 的活。

    两条腿都认：DOI 命中，或归一后的标题命中。任一命中即算「有」——
    宁可多标一篇「你已经有了」让人去核实，也别让人重复下载重复精读。
    """
    n = 0
    for p in papers or []:
        doi = (p.get('doi') or '').strip().lower()
        hit = bool(doi and doi in have_dois) or (norm_title(p.get('title')) in have_titles)
        p['in_library'] = hit
        if hit:
            n += 1
    return n
