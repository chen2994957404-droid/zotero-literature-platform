# -*- coding: utf-8 -*-
"""snowball · 引用雪球基础件（公理：种子文献 → 沿引用网络扩展出的相关文献）

**为什么必须有这块（有实证支撑，不是拍脑袋）**：
系统综述领域的实测研究给出了明确数字 ——

    单个数据库检索              召回率 13~35%
    + 优化检索式                召回率 50~95%   ← 我们的 query_expand 做到这层
    + 一轮前后向雪球            召回率 90~100%  ← 本模块补的就是这一步

也就是说，**只靠关键词检索，必然漏掉相当一部分相关文献**，
而漏掉的那批往往用了完全不同的术语 —— 但它们在引用网络上就挨着。

两个方向作用不同（别只做一边）：
  backward（后向，查参考文献）→ **提召回**，找到这个方向的源头与奠基工作
  forward （前向，查被引）    → **提精度**，找到跟进者与最新进展

## 选型：为什么用 OpenAlex 而不是 Sciverse（实测得出，非直觉）

| | Sciverse meta-paper-relations | OpenAlex |
|---|---|---|
| 返回内容 | 只有 OpenAlex ID，**标题为空、无 DOI** | 标题/DOI/年份/被引数俱全 |
| 取一篇种子的 49 条参考文献 | 需再查 49 次 | **一次批量请求 1.0 秒** |
| 限流 | 30 次/分钟 | 免费无密钥 |

按直觉「既然用了 Sciverse 就一路用到底」会做出一个
「一篇种子要 3 分钟还拿不到标题」的废功能。**这个结论只能测出来。**

对外接口：
  - expand(dois, direction, limit)  → 雪球扩展，返回结构化文献列表
  - work_by_doi(doi)               → 取一篇文献的 OpenAlex 记录

依赖：Python 标准库。OpenAlex 免费、无需密钥。
礼貌起见在 User-Agent 里带联系方式（OpenAlex 官方推荐做法，可进"礼貌池"享更好配额）。
"""
import os, sys, json, time, urllib.request, urllib.parse, urllib.error

from core import errors
from adapters import openalex

# HTTP、重试、摘要还原、字段归一，统一由 adapters.openalex 负责 ——
# 重构前这些在 snowball / paper_discovery / find_papers 里各有一份（阶段 2 合并）。
OPENALEX = openalex.BASE
UA = openalex.UA
FIELDS = openalex.FIELDS


class SnowballError(errors.ExternalServiceError):
    """雪球扩展失败。归入 ExternalServiceError：多半是 OpenAlex 那边的问题，可重试。"""


def _get(url, timeout=45, retries=2):
    """GET + 退避重试。实现在 adapters.openalex，这里只把异常翻译成 SnowballError。"""
    try:
        return openalex.get(url, timeout=timeout, retries=retries)
    except errors.PlatformError as e:
        raise SnowballError(str(e)) from e


def _abstract(inv):
    """OpenAlex 摘要是倒排索引，还原成正常文本（实现见 adapters.openalex）。"""
    return openalex.restore_abstract(inv)


def _norm(w):
    """OpenAlex work → 本平台统一的文献字典（归一在 adapters.openalex，这里只补 unique_id）。"""
    d = openalex.normalize(w)
    d['unique_id'] = f"paper:{d['doi']}" if d['doi'] else ''
    return d


def work_by_doi(doi):
    """按 DOI 取 OpenAlex 记录。查不到返回 None（不抛异常，便于批量跳过）。"""
    doi = (doi or '').strip().replace('https://doi.org/', '')
    if not doi:
        return None
    try:
        return _get(f'{OPENALEX}/works/doi:{urllib.parse.quote(doi)}')
    except SnowballError:
        return None


def _backward(work, limit):
    """后向：这篇引用了谁。**批量取元数据**，一次最多 50 条。"""
    refs = [r.split('/')[-1] for r in (work.get('referenced_works') or [])][:limit]
    out = []
    for i in range(0, len(refs), 50):
        ids = '|'.join(refs[i:i + 50])
        d = _get(f'{OPENALEX}/works?filter=openalex_id:{ids}'
                 f'&per-page=50&select={FIELDS}')
        out += [_norm(w) for w in d.get('results', [])]
        time.sleep(0.2)
    return out


def _forward(work, limit):
    """前向：谁引用了这篇。按被引数降序，先看影响力大的跟进工作。"""
    wid = (work.get('id') or '').split('/')[-1]
    if not wid:
        return []
    out = []
    per = min(50, max(1, limit))
    d = _get(f'{OPENALEX}/works?filter=cites:{wid}&per-page={per}'
             f'&sort=cited_by_count:desc&select={FIELDS}')
    out += [_norm(w) for w in d.get('results', [])]
    return out[:limit]


def expand(dois, direction='both', limit_per_seed=40, on_progress=None):
    """从种子文献出发做雪球扩展。

    dois          : 种子的 DOI 列表（通常来自用户库里与主题最相关的几篇）
    direction     : 'backward' / 'forward' / 'both'
    limit_per_seed: 每篇种子每个方向最多取多少条

    返回 {'items': [...], 'stats': [(doi, 后向数, 前向数, 说明)]}
    items 与 sciverse.search_papers 的结构一致，可直接进 lib_match 对照。

    **种子集质量决定雪球效果**（实证研究的结论）——
    所以调用方应该用 lib_match 挑出真正相关的几篇当种子，而不是随便拿几篇。
    """
    items, seen, stats = [], set(), []
    for doi in dois:
        w = work_by_doi(doi)
        if not w:
            stats.append((doi, 0, 0, '在 OpenAlex 查不到这篇'))
            continue
        nb = nf = 0
        try:
            if direction in ('backward', 'both'):
                for it in _backward(w, limit_per_seed):
                    k = it['doi'].lower() or it['openalex_id']
                    if k and k not in seen:
                        seen.add(k)
                        it['from'] = 'backward'
                        items.append(it)
                        nb += 1
            if direction in ('forward', 'both'):
                for it in _forward(w, limit_per_seed):
                    k = it['doi'].lower() or it['openalex_id']
                    if k and k not in seen:
                        seen.add(k)
                        it['from'] = 'forward'
                        items.append(it)
                        nf += 1
            stats.append((doi, nb, nf, (w.get('title') or '')[:56]))
        except SnowballError as e:
            stats.append((doi, nb, nf, f'部分失败: {str(e)[:40]}'))
        if on_progress:
            on_progress(doi, nb, nf)
        time.sleep(0.3)          # 对 OpenAlex 友好
    return {'items': items, 'stats': stats}
