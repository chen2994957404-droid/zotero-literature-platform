# -*- coding: utf-8 -*-
"""litsearch · 对抗式检索的**原料通道**：精确检索 / 取摘要 / 雪球 / 我有没有。

## 解决的真实问题

`tools/discover` 是「机器排好序 → 人看编号挑 → 人点收取」。那套流程假设**人**是
读清单的那一方。2026-09-09 用户提出他真正要的是**对抗式检索**：
先想 → 去取 → 总结 → 发现缺什么 → 再取，循环到答案成型，**中间的判断由 agent 做**。

那套循环不需要「拆检索式」和「排序」——
agent 会自己想检索式（还能根据上一轮读到的东西调整），也会读摘要自己判断贴题度。
它只要有人把**干净的原料**递到手上。本工具就是那个通道。

## 为什么单独成包，而不是加进 discover

`discover` 整包标着 `costs_money = true` + 写 Zotero，守卫要求它注册的每个 tool
**都必须弹窗确认**。而对抗式检索一轮要调十几次，每次弹窗等于把这个用法废掉
（同样的道理见 `host/mcp/server.py` 里 `fulltext_status` 那条注释：
「只读的东西不该被工具包的档位连坐」）。

所以本包**整包免费、只读、不写任何东西**，这样才能注册成不弹窗的 tool。

## 四个动作

| 函数 | 干什么 | 代价 |
|---|---|---|
| `search(term)` | **精确检索**：词必须出现在标题或摘要，不是模糊相关性 | 免费 |
| `abstract(doi)` | 取一篇的完整摘要（判断贴题度的主要依据） | 免费 |
| `cited_by(doi)` | 谁引了这篇（前向雪球） | 免费 |
| `references(doi)` | 这篇引了谁（后向雪球） | 免费 |

每个返回里都带 `in_library` —— 「这篇我是不是早就有了」。
判断在 `shared/domain/libmatch`，取库存在 `shared/adapters/zotero_client`。

## 为什么默认用精确检索而不是相关性检索

2026-09-09 实测：同一个问题，OpenAlex 的相关性检索（`search`）返回的前十条
全是不相干的高被引大综述；换成 `title_and_abstract.search`（**词必须真的出现**），
`borosiloxane` 命中 112 篇、`Si-O-B` 命中 247 篇，去重后 365 篇就是那个领域的全部版图。
对抗式检索要的是**干净可枚举的召回**，不是一个猜出来的排序。

## 它不做什么（都是刻意的）

- **不排序** —— 贴题度由调用方读摘要自己判断。排序要向量库和本地模型，
  算不出来时会静默退化成「按被引量排」（踩坑 #149），那比不排更坏。
- **不拆检索式** —— 那要花钱，且 agent 自己想的更贴当下这一轮。要它去 `tools/discover`。
- **不写 Zotero** —— 收进库是 `tools/getpdf --to-zotero`（它连 PDF 一起挂）。
- **不取全文** —— 那是 `tools/getpdf` 的 `fulltext`（四层回退）+ `tools/library` 的按节取原文。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import time

from shared.adapters import openalex, snowball
from shared.adapters.zotero_client import library_index
from shared.domain.libmatch import mark_have

# 库索引缓存：一轮对抗式检索会连着调好几次，别每次都去拉一遍 Zotero。
# （`tools/discover` 里有一份同样口径的缓存 —— 两个工具不许互相 import，
#   所以各留一份 5 行的缓存，比为它建个共用件更划算。要是出现第三个使用者，
#   就该把「带缓存的库索引」提到 `shared/adapters/zotero_client` 里去。）
CACHE_TTL = 300
_index_cache = {'t': 0, 'titles': set(), 'dois': set()}

# 一次最多给多少条。**200 是 OpenAlex 单页的真实上限**，不是我们拍的数。
#
# ⚠ 2026-09-10 从 100 提到 200，理由是用户那句话：
# 「现在 LLM 自己也能检索到合适的论文，中间这层会不会反而限制它」。
# 分界线在这里：**递事实 = 增强，替判断 = 限制**。
# 「这个领域一共 112 篇」是事实，那就应该一次能捞干净；
# 把它切成 100 篇一页，是我们替调用方决定了「先看这些就够了」。
MAX_LIMIT = 200


def _index(force=False):
    """库里已有的（归一标题集合, DOI 集合）。Zotero 没开时返回两个空集合。"""
    now = time.time()
    if not force and _index_cache['t'] and now - _index_cache['t'] < CACHE_TTL:
        return _index_cache['titles'], _index_cache['dois']
    titles, dois = library_index()      # 没开/没配时它自己降级成空集合，不抛异常
    _index_cache.update({'t': now, 'titles': titles, 'dois': dois})
    return titles, dois


def _finish(items, limit):
    """统一收尾：截断 → 标「我有没有」→ 返回。"""
    items = list(items or [])[:max(1, min(int(limit), MAX_LIMIT))]
    titles, dois = _index()
    mark_have(items, titles, dois)
    return items


def search(term, limit=25, year_from=None, year_to=None):
    """**精确检索**：`term` 必须出现在标题或摘要里。

    term  : 检索词。支持 OpenAlex 的检索语法 —— 词组加引号（`"boronic acid"`）、
            多词用 AND（`"phenylboronic acid" AND siloxane`）。
    返回 [{title, doi, year, venue, citations, abstract, is_oa, oa_url, in_library}]，
    外加一个整数总命中数（可能远大于返回条数 —— 那正是「这个领域有多大」的答案）。

    返回 `(items, total)`。**total 比 items 有用**：它告诉你这个词在全世界有多少篇，
    从而知道该收窄还是放宽。
    """
    if not (term or '').strip():
        return [], 0
    f = {'title_and_abstract.search': term}
    if year_from and year_to:
        f['publication_year'] = f'{int(year_from)}-{int(year_to)}'
    elif year_from:
        f['publication_year'] = f'>{int(year_from) - 1}'
    elif year_to:
        f['publication_year'] = f'<{int(year_to) + 1}'
    items, total = openalex.works_by_filter(
        f, limit=max(1, min(int(limit), MAX_LIMIT)), sort='publication_year:desc')
    return _finish(items, limit), total


def abstract(doi):
    """取一篇的完整记录，**摘要不截断**。查不到返回 None。

    对抗式检索里这一步最要紧 —— 判断一篇贴不贴题、有没有配方，
    靠的就是读摘要，而不是看标题猜。

    ⚠ 和 `search()` 的分工是刻意的：列表里给**预览**（截到 1500 字，省上下文，
    并如实标 `abstract_truncated`），这里给**全文摘要**。
    「我要完整看这一篇」的时候再截断，就是替调用方判断「剩下的不重要」——
    而剩下的常常正是方法那一段（2026-09-10 实战里那条决定性证据就藏在靠后位置）。
    """
    w = openalex.work_by_doi(doi)
    if not w:
        return None
    item = openalex.normalize(w)
    item['abstract'] = openalex.restore_abstract(
        w.get('abstract_inverted_index'), limit=0)
    item['abstract_truncated'] = False
    return _finish([item], 1)[0]


def cited_by(doi, limit=50):
    """谁引了这篇（前向雪球）—— 找「这个方向后来怎么发展的」。"""
    r = snowball.expand([doi], direction='forward', limit_per_seed=min(int(limit), MAX_LIMIT))
    return _finish(r.get('items'), limit)


def references(doi, limit=50):
    """这篇引了谁（后向雪球）—— 找「这个方向的根在哪」。"""
    r = snowball.expand([doi], direction='backward', limit_per_seed=min(int(limit), MAX_LIMIT))
    return _finish(r.get('items'), limit)
