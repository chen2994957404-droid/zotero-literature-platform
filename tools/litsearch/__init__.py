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

## 动作

| 函数 | 干什么 | 代价 |
|---|---|---|
| `search(term)` | **精确检索**：词必须出现在标题或摘要，不是模糊相关性 | 免费额度内 |
| `semantic(text= / like=)` | **按意思检索**：一段话，或「照着这几篇找相似的」（2026-09-26 加） | $0.001/次，免费额度 ≈1000 次/天 |
| `abstract(doi)` | 取一篇的完整摘要（OpenAlex 没有就回退证据库原文 → S2） | 免费 |
| `cited_by(doi)` / `references(doi)` | 前向 / 后向雪球（单篇） | 免费额度内 |
| `snowball_many(dois)` | 一次多篇雪球，标每篇**连到几个种子** | 免费额度内 |
| `hide_seen(items)` | 带台账时只留新的 | 本地 |

检索类函数都收一个可选的 `session`（检索台账名，见 `session.py`）：给了就自动记账、
每条带上 `ledger` 状态（新 / 第几轮见过 / 已判）；不给 = 原来的行为，一点不变。

## 多轮全面检索（2026-09-26，规划见 `docs/reference/检索全面性_改造规划.md`）

一轮 = 词面（`search`）+ 语义（`semantic`）+ 引用（`snowball_many`）三条腿 → agent 按条判相关
（`session.judge`）→ 看饱和与估计（`session.status`）→ 从相关篇里挖新说法（`session.mine_terms`）→ 下一轮。
三条腿缺一不可：语义补「换了说法」，词面与引用补「没摘要的只能按标题匹配」（踩坑 #188）。

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
import io
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

import re
import time

from collections import Counter

from shared.adapters import openalex, snowball
from shared.kernel import errors, paths
from shared.adapters.zotero_client import library_index
from shared.domain.libmatch import looks_like_book, mark_have
from tools.litsearch import session as ledger

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


# 不是论文的条目（2026-09-26 验收：审稿决定信、作者回复、figshare / Zenodo 数据集混进结果，
# 每条都要 agent 判一遍，白花工夫）。按 OpenAlex 的 type 认，没有 type 的（Sciverse 退路）按 DOI 形状认
NONPAPER_TYPES = {'peer-review', 'dataset', 'paratext', 'erratum', 'supplementary-materials', 'retraction'}
_NONPAPER_DOI = re.compile(r'(/v\d+/(decision|review|response|author-response)\d*$)|(/(decision|review)\d+$)'
                           r'|^10\.6084/|^10\.5281/')


def is_nonpaper(it):
    """审稿记录、数据集、勘误这类不是论文的条目。"""
    if (it.get('type') or '') in NONPAPER_TYPES:
        return True
    return bool(_NONPAPER_DOI.search((it.get('doi') or '').lower()))


def _finish(items, limit):
    """统一收尾：剔除非论文 → 截断 → 标「我有没有」→ 标「能不能立刻读」→ 标「像不像书」→ 返回。"""
    items = [it for it in (items or []) if not is_nonpaper(it)]
    items = items[:max(1, min(int(limit), MAX_LIMIT))]
    titles, dois = _index()
    mark_have(items, titles, dois)
    mark_readable(items)
    for it in items:
        it['bookish'] = looks_like_book(it)     # 摆事实不过滤：模型自己决定要不要读书章节
        it['has_abstract'] = bool(it.get('abstract'))   # Elsevier 大多没有（踩坑 #188）：判相关时要知道只凭标题
    return items


def _log_ledger(items, session, channel, term='', total=None, seed='', calls=1):
    """带台账时记账，并给每条挂上记账前的状态 `ledger`（新 / 见过 / 已判）。不带台账原样返回。"""
    if session:
        for it, st in zip(items, ledger.record(session, channel, items, term=term, total=total,
                                               seed=seed, calls=calls)):
            it['ledger'] = st
    return items


def hide_seen(items):
    """只留台账里新出现的（`ledger.new`）。返回 (新的, 藏掉的篇数)。没带台账的条目一律当新的。"""
    kept = [it for it in items if (it.get('ledger') or {'new': True}).get('new')]
    return kept, len(items) - len(kept)


def _year_filter(year_from, year_to):
    """年份范围 → OpenAlex publication_year 的写法；都没给返回 None。"""
    if year_from and year_to:
        return f'{int(year_from)}-{int(year_to)}'
    if year_from:
        return f'>{int(year_from) - 1}'
    if year_to:
        return f'<{int(year_to) + 1}'
    return None


def _from_sciverse(term, limit, year_from, year_to):
    """OpenAlex 限流时的退路：Sciverse 语义检索。**形状对齐成 (items, total)**，调用方不用分辨来源。

    两个检索接口的返回形状本来不一样（`sciverse.search_papers` 给 dict，本函数给元组），
    2026-09-14 真实任务里脚本因此崩过一次 —— 在这里统一，别让调用方各接一种。
    """
    from shared.adapters import sciverse
    r = sciverse.search_papers(term, limit=limit, year_from=year_from, year_to=year_to)
    items = r['items'] if isinstance(r, dict) else list(r or [])
    total = (r.get('total') if isinstance(r, dict) else None) or len(items)
    for it in items:
        it.setdefault('publisher', '')
        it.setdefault('oa_status', '')
        it['source'] = 'sciverse'
    return items, total


def _log_search(term, total, items, source, filters):
    """检索留档（PRISMA-S 的精神）：每次检索一行 jsonl，报告里「搜过哪些说法、各多少」有据可查。

    `discover` 有自己的整份留档；`lit_search` 是一条条的原子检索，用追加式日志更合适。
    写不下就算了，不影响检索。
    """
    import json
    import time
    try:
        path = paths.search_record('litsearch_' + time.strftime('%Y%m%d'), create_dir=True)
        path = path[:-5] + '.jsonl'
        rec = {'time': time.strftime('%H:%M:%S'), 'term': term, 'total': total, 'source': source,
               'filters': filters, 'top': [(it.get('doi') or it.get('title') or '')[:120] for it in items[:10]]}
        with io.open(path, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except OSError:
        pass


def mark_readable(items):
    """给每条加 `readable`：证据库里已经解析出全文（`library_outline` 立刻能点）。

    2026-09-14 加：「库里有」不等于「能读」—— 有条目没正本、有正本没解析都读不了。
    模型据此先读手上现成的，再去取没有的。
    """
    from shared.kernel import catalog
    by_doi = catalog.by_doi()
    for it in items:
        pid = by_doi.get(catalog.norm_doi(it.get('doi') or ''), '')
        it['db_id'] = pid
        it['readable'] = bool(pid) and os.path.exists(paths.fulltext(pid))
    return items


def search(term, limit=25, year_from=None, year_to=None, session=None):
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
    yf = _year_filter(year_from, year_to)
    if yf:
        f['publication_year'] = yf
    source = 'openalex'
    try:
        items, total = openalex.works_by_filter(
            f, limit=max(1, min(int(limit), MAX_LIMIT)), sort='publication_year:desc')
    except errors.RateLimited as e:
        # 2026-09-14 真实任务：没配 OPENALEX_KEY 跑 3 条就 429。有 Sciverse 密钥就退过去，
        # 没有就把原话抛出去（里面写着去哪领 key）。退路是语义检索，命中口径不同，结果里标明。
        try:
            items, total = _from_sciverse(term, limit, year_from, year_to)
            source = 'sciverse(退路)'
        except Exception:
            raise e
    items = _finish(items, limit)
    _log_search(term, total, items, source, {'year_from': year_from, 'year_to': year_to})
    _log_ledger(items, session, 'keyword', term=term, total=total)
    return items, total

def _abstract_from_fulltext(pid):
    """证据库里解析过的原文 → 摘要段（有「Abstract」标题就取它下面那段，否则取引言之前的正文）。取不到返回 ''。"""
    try:
        text = io.open(paths.fulltext(pid), encoding='utf-8').read()
    except OSError:
        return ''
    lines = text.split('\n')
    for i, ln in enumerate(lines):
        if re.match(r'^\s*#*\s*\**\s*abstract\b', ln, re.I):
            body = []
            for nxt in lines[i + 1:]:
                if nxt.lstrip().startswith('#') and body:
                    break
                if nxt.strip():
                    body.append(nxt.strip())
            rest = re.sub(r'^\s*#*\s*\**\s*abstract\**[:.\s]*', '', ln, flags=re.I).strip()
            return ' '.join(([rest] if rest else []) + body)[:4000]
    body = []
    for ln in lines[1:]:
        if re.match(r'^\s*#+.*introduction', ln, re.I):
            break
        if ln.strip() and not ln.lstrip().startswith(('#', '!', '|')):
            body.append(ln.strip())
    return ' '.join(body)[:2000]


def abstract(doi):
    """取一篇的完整记录，**摘要不截断**。查不到返回 None。

    对抗式检索里这一步最要紧 —— 判断一篇贴不贴题、有没有配方，
    靠的就是读摘要，而不是看标题猜。

    ⚠ 和 `search()` 的分工是刻意的：列表里给**预览**（截到 1500 字，省上下文，
    并如实标 `abstract_truncated`），这里给**全文摘要**。
    「我要完整看这一篇」的时候再截断，就是替调用方判断「剩下的不重要」——
    而剩下的常常正是方法那一段（2026-09-10 实战里那条决定性证据就藏在靠后位置）。

    OpenAlex 没摘要时（Elsevier 居多，踩坑 #188）依次回退：证据库原文 → Semantic Scholar。
    `abstract_source` 如实写来源（openalex / fulltext / s2 / none）。
    """
    w = openalex.work_by_doi(doi)
    if not w:
        return None
    item = openalex.normalize(w)
    item['abstract'] = openalex.restore_abstract(
        w.get('abstract_inverted_index'), limit=0)
    item['abstract_truncated'] = False
    item['abstract_source'] = 'openalex' if item['abstract'] else 'none'
    item = _finish([item], 1)[0]
    if not item['abstract'] and item.get('readable'):
        item['abstract'] = _abstract_from_fulltext(item['db_id'])
        if item['abstract']:
            item['abstract_source'] = 'fulltext'
    if not item['abstract'] and item.get('doi'):
        try:
            from shared.adapters import semanticscholar
            rec = semanticscholar.papers([item['doi']]).get(item['doi'].lower()) or {}
            if rec.get('abstract'):
                item['abstract'], item['abstract_source'] = rec['abstract'], 's2'
        except errors.PlatformError:
            pass
    item['has_abstract'] = bool(item['abstract'])
    return item


def cited_by(doi, limit=50, year_from=None, newest_first=False, session=None):
    """谁引了这篇（前向雪球）—— 找「这个方向后来怎么发展的」。

    `newest_first=True`：按年份新到旧（找最新进展用；默认按被引，刚发表的新工作会被压到最后）。
    """
    r = snowball.expand([doi], direction='forward', limit_per_seed=min(int(limit), MAX_LIMIT),
                        year_from=year_from,
                        forward_sort='publication_year:desc' if newest_first else 'cited_by_count:desc')
    items = _finish(r.get('items'), limit)
    return _log_ledger(items, session, 'cited_by', seed=doi)


def references(doi, limit=50, year_from=None, session=None):
    """这篇引了谁（后向雪球）—— 找「这个方向的根在哪」。"""
    r = snowball.expand([doi], direction='backward', limit_per_seed=min(int(limit), MAX_LIMIT),
                        year_from=year_from)
    items = _finish(r.get('items'), limit)
    return _log_ledger(items, session, 'references', seed=doi)


# 一次多篇雪球的种子上限：一篇前后向约 7 秒，4 路并发下 10 篇约 20 秒，给 MCP 约 60 秒的超时留余量
SNOWBALL_MAX_SEEDS = 10


def snowball_many(dois, direction='both', limit_per_seed=50, year_from=None, newest_first=False,
                  limit=100, session=None):
    """一次对多篇做雪球，按**连到几个种子**排（多篇相关文章都引 / 都被它引的最该先看）。

    这是排序，但只按可数的事实，不猜贴题度 —— 不违反本包「不替判断」的原则。
    返回 `(items, stats)`：每条带 `seed_links`（连到几个种子）与 `seed_dirs`（经由哪个方向）；
    stats 是每个种子的 (doi, 后向数, 前向数, 说明)。
    """
    dois = [d for d in dict.fromkeys((d or '').strip() for d in dois or []) if d]
    if not dois:
        raise errors.BadInputError('至少给一篇种子的 DOI')
    if len(dois) > SNOWBALL_MAX_SEEDS:
        raise errors.BadInputError(
            f'一次最多 {SNOWBALL_MAX_SEEDS} 篇种子（再多会超过约 60 秒的调用超时）；请分几次调')
    seed_keys = {ledger.key_of({'doi': d}) for d in dois}
    links, dirs, first, stats = Counter(), {}, {}, []
    sort = 'publication_year:desc' if newest_first else 'cited_by_count:desc'
    import concurrent.futures as cf

    def one(d):
        return snowball.expand([d], direction=direction, limit_per_seed=min(int(limit_per_seed), MAX_LIMIT),
                               year_from=year_from, forward_sort=sort)

    # 种子之间并发（实测一篇前后向约 7 秒，10 篇串行会超过 MCP 的 60 秒）；4 路对 OpenAlex 的普通列表查询不算多
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(one, dois))
    for r in results:
        stats.extend(r.get('stats') or [])
        for it in r.get('items') or []:
            k = ledger.key_of(it)
            if k in seed_keys:
                continue
            links[k] += 1
            dirs.setdefault(k, set()).add(it.get('from') or '')
            first.setdefault(k, it)
    order = sorted(first, key=lambda k: (-links[k], -(first[k].get('year') or 0)))
    items = []
    for k in order:
        it = first[k]
        it['seed_links'] = links[k]
        it['seed_dirs'] = sorted(x for x in dirs[k] if x)
        items.append(it)
    items = _finish(items, limit)
    if session:
        # 按方向分开记账：前向算 cited_by、后向算 references（捕获–再捕获要分清渠道）
        for ch, key in (('cited_by', 'forward'), ('references', 'backward')):
            part = [it for it in items if key in it['seed_dirs']]
            if part:
                states = ledger.record(session, ch, part, seed=','.join(dois))
                for it, st in zip(part, states):
                    it.setdefault('ledger', st)
    return items, stats


# ── 语义检索（2026-09-26）────────────────────────────────────────────────
# 限制见 shared/adapters/openalex 的 semantic_search：每次 ≤50 条、不能翻页、不按年份排、输入 ≤1500 字。
SEMANTIC_MAX_CALLS = 8      # 一次工具调用最多发几次语义检索：并发错开 1.1 秒发，实测 9 次 31 秒（2026-09-26），8 次给 MCP 的 60 秒超时留余量
SEMANTIC_MAX_SLICES = 6
SEMANTIC_MAX_LIKE = 5
SEMANTIC_MAX_UNLIKE = 3
_RRF_K = 60                 # 倒数名次融合的常数（Cormack et al. 2009 的通行取值）


def year_windows(year_from, year_to, slice_by_year=False, this_year=None):
    """年份范围 → 要分别检索的窗口列表 [(起, 止)]。不切片或没给起始年时只有一个窗口。

    切片的理由：语义检索每次最多 50 条、不能翻页，要更多只能按年份切开分几次搜。
    超过 6 年时切成 6 段大致等长的区间。只给起始年时止于今年。
    """
    if not slice_by_year or not year_from:
        return [(year_from, year_to)]
    end = int(year_to or this_year or time.localtime().tm_year)
    years = list(range(int(year_from), end + 1))
    if not years:
        return [(year_from, year_to)]
    n = min(len(years), SEMANTIC_MAX_SLICES)
    size, extra = divmod(len(years), n)
    out, i = [], 0
    for j in range(n):
        step = size + (1 if j < extra else 0)
        out.append((years[i], years[i + step - 1]))
        i += step
    return out


def rrf_fuse(pos_lists, neg_lists=()):
    """倒数名次融合（RRF）：多个结果列表 → 一个排序。被越多列表、越靠前召回的越靠前；
    负例列表里出现的扣分。每条带 `semantic_hits`（被几个正例列表召回）。纯函数。"""
    score, first, hits = {}, {}, Counter()
    for lst in pos_lists:
        for r, it in enumerate(lst):
            k = ledger.key_of(it)
            score[k] = score.get(k, 0.0) + 1.0 / (_RRF_K + r + 1)
            first.setdefault(k, it)
            hits[k] += 1
    for lst in neg_lists:
        for r, it in enumerate(lst):
            k = ledger.key_of(it)
            if k in score:
                score[k] -= 1.0 / (_RRF_K + r + 1)
    out = []
    for k in sorted(score, key=lambda k: -score[k]):
        it = first[k]
        it['semantic_hits'] = hits[k]
        out.append(it)
    return out


def _exemplar_text(doi):
    """一篇种子 → 语义检索的输入（标题 + 摘要）。返回 (text, has_abstract)；查不到返回 (None, False)。"""
    w = openalex.work_by_doi(doi)
    if not w:
        return None, False
    abs_ = openalex.restore_abstract(w.get('abstract_inverted_index'), limit=0)
    return ((w.get('title') or '') + '. ' + abs_).strip(), bool(abs_)


def semantic(text='', like=(), unlike=(), year_from=None, year_to=None, slice_by_year=False,
             limit=25, session=None):
    """**按意思检索**。两种输入可单用可合用：

    text   : 一段话描述要找什么（英文，官方说一段话比几个词好）
    like   : 「照着这几篇找」—— DOI 列表（≤5），每篇用它的标题 + 摘要单独检索一次，结果按 RRF 融合；
             这就是相关反馈，调用方不用把摘要搬进上下文。种子本身不出现在结果里
    unlike : 「别要像这几篇的」—— DOI 列表（≤3），跟它们像的往后排

    年份：`slice_by_year=True` 时按年切片（≤6 片），每片各取 50 条 —— 突破「每次最多 50 条」。
    ⚠ 语义检索**不按年份排序**，要新文章必须给年份范围。

    返回 `(items, info)`；info = {calls, windows, truncated, exemplars_without_abstract, missing, pool}。
    """
    like = [d for d in dict.fromkeys((d or '').strip() for d in like or []) if d]
    unlike = [d for d in dict.fromkeys((d or '').strip() for d in unlike or []) if d]
    text = (text or '').strip()
    if not text and not like:
        raise errors.BadInputError('给一段话（text），或给几篇 DOI（like）让我照着找')
    if len(like) > SEMANTIC_MAX_LIKE or len(unlike) > SEMANTIC_MAX_UNLIKE:
        raise errors.BadInputError(
            f'like 最多 {SEMANTIC_MAX_LIKE} 篇、unlike 最多 {SEMANTIC_MAX_UNLIKE} 篇；想用更多就分几次调')
    windows = year_windows(year_from, year_to, slice_by_year)
    n_inputs = (1 if text else 0) + len(like) + len(unlike)
    calls = n_inputs * len(windows)
    if calls > SEMANTIC_MAX_CALLS:
        raise errors.BadInputError(
            f'这样要发 {calls} 次语义检索（输入 {n_inputs} 条 × {len(windows)} 个年份窗口），'
            f'一次最多 {SEMANTIC_MAX_CALLS} 次（防超时）。少给几篇种子，或少切几片年份')
    queries, missing, no_abs = [], [], []
    if text:
        queries.append(text)
    for d in like:
        t, has = _exemplar_text(d)
        if t is None:
            missing.append(d)
            continue
        if not has:
            no_abs.append(d)
        queries.append(t)
    neg = []
    for d in unlike:
        t, _has = _exemplar_text(d)
        if t is None:
            missing.append(d)
        else:
            neg.append(t)
    if not queries:
        raise errors.BadInputError('给的种子在 OpenAlex 里都查不到：' + ', '.join(missing))
    calls = (len(queries) + len(neg)) * len(windows)
    jobs, is_pos = [], []
    for yf, yt in windows:
        y = _year_filter(yf, yt)
        # 审稿意见记录（Crossref 的 peer-review 类型，标题形如「Review for "…"」）不是论文：
        # 2026-09-26 实测一次语义检索 50 条里混进 5 条，默认排除（is_paratext 语义检索不支持，只能按 type 排）
        filt = {'type': '!peer-review'}
        if y:
            filt['publication_year'] = y
        jobs += [(q, filt) for q in queries] + [(q, filt) for q in neg]
        is_pos += [True] * len(queries) + [False] * len(neg)
    results = openalex.semantic_many(jobs)      # 并发发出（单次 5–8 秒，串行会超过 MCP 的 60 秒）
    pos_lists = [got for (got, _c), p in zip(results, is_pos) if p]
    neg_lists = [got for (got, _c), p in zip(results, is_pos) if not p]
    truncated = any(c for (_g, c), p in zip(results, is_pos) if p)
    seeds = {ledger.key_of({'doi': d}) for d in like + unlike}
    fused = [it for it in rrf_fuse(pos_lists, neg_lists) if ledger.key_of(it) not in seeds]
    items = _finish(fused, limit)
    term = (text[:200] + (' | ' if text and like else '')) + ('like:' + ','.join(like) if like else '')
    _log_search('[semantic] ' + term, len(fused), items, 'openalex-semantic',
                {'year_from': year_from, 'year_to': year_to, 'windows': windows})
    _log_ledger(items, session, 'semantic', term=term, total=len(fused), seed=','.join(like), calls=calls)
    return items, {'calls': calls, 'windows': windows, 'truncated': truncated,
                   'exemplars_without_abstract': no_abs, 'missing': missing, 'pool': len(fused)}
