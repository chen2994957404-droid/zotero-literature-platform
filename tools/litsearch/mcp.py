# -*- coding: utf-8 -*-
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass
"""litsearch 的 MCP 面：只读检索 + 检索台账（模型可以自己调，不写 Zotero、不弹窗）。

**本文件只做参数转换**：把 MCP 传来的 arguments 拆成 Python 参数、把返回值渲染成文本。
一行业务逻辑都不许写在这里 —— 逻辑在 `tools/litsearch/__init__.py` 与 `session.py`，
这样命令行与 MCP 两个入口共用同一份行为。

**为什么不加 confirm**：本包只读公开数据，台账只写自己的本地状态文件（可重建层），
不属于「花钱或有副作用」那一档。多轮检索一轮要调十几次，每次弹窗等于废掉这个用法。
语义检索每次 $0.001，在 OpenAlex 免费 key 的每天 $1 额度内（≈1000 次）。
"""
import json

from tools import litsearch
from tools.litsearch import session as ledger

_DOI = {'doi': {'type': 'string', 'description': '文献的 DOI，如 10.1021/ma500632f'}}
_LIMIT = {'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200,
                    'description': '返回条数上限（200 是 OpenAlex 单页的真实上限），'
                                   '默认见各工具'}}
_SESSION = {
    'session': {'type': 'string',
                'description': '检索台账名（可选，同一个研究问题用同一个名字，先用 lit_session 建）。'
                               '给了就自动记账：每条标【新】/【见过】/【已判】，跨轮不重复'},
    'onlyNew': {'type': 'boolean',
                'description': '配合 session：只列台账里没见过的（省上下文）。默认 false'},
}
_YEARS = {'yearFrom': {'type': 'integer', 'description': '起始年份（含）'},
          'yearTo': {'type': 'integer', 'description': '结束年份（含）'}}

_OA_WORDS = {'closed': '付费', 'hybrid': '混合', 'gold': 'OA', 'diamond': 'OA',
             'green': 'OA·存档', 'bronze': 'OA·免费读'}
_VERDICT_WORDS = {'relevant': '相关', 'partial': '部分', 'irrelevant': '不相关', 'unsure': '没法判'}


def _list(v):
    """数组参数：列表原样；JSON 字符串或逗号分隔的字符串也认（有的客户端会把数组传成字符串）。"""
    if v is None or v == '':
        return []
    if isinstance(v, (list, tuple)):
        return list(v)
    s = str(v).strip()
    if s.startswith('['):
        try:
            return list(json.loads(s))
        except ValueError:
            pass
    return [x.strip() for x in s.split(',') if x.strip()]


def _ledger_mark(it):
    st = it.get('ledger')
    if not st:
        return ''
    if st.get('new'):
        return '【新】'
    v = st.get('verdict')
    if v:
        return '【已判:%s】' % _VERDICT_WORDS.get(v, v)
    return '【见过·第%s轮】' % st.get('first_round')


def _line(it):
    """一条结果渲染成一行（带「库里有没有」+ 出版商 + 付不付费 + 台账状态）。

    出版商和付费状态是**事实**，摆出来让模型按用户的路线挑；不在这里过滤。
    """
    # 三档：可读（已解析，library_outline 立刻能点）> 库里有（有条目，先 paper_fulltext）> 新
    mark = ('【可读:%s】' % it.get('db_id') if it.get('readable') else
            '【库里有】' if it.get('in_library') else '         ')
    mark = _ledger_mark(it) + mark
    if it.get('bookish'):
        mark += '[书/词条]'
    if not it.get('has_abstract', True):
        mark += '【无摘要】'
    if it.get('seed_links'):
        mark += '[连%d个种子]' % it['seed_links']
    if (it.get('semantic_hits') or 0) > 1:
        mark += '[%d路召回]' % it['semantic_hits']
    pub = (it.get('publisher') or '').replace(
        'Multidisciplinary Digital Publishing Institute', 'MDPI')
    oa = _OA_WORDS.get(it.get('oa_status') or '', '')
    tail = ' · '.join(x for x in ((it.get('venue') or '?')[:40], pub[:28], oa) if x)
    ref = it.get('doi') or ('%s（无 DOI，判断时用这个键）' % ledger.key_of(it))
    return '%s [%s] 被引%-5s %s\n           %s | %s' % (
        mark, it.get('year') or '????', it.get('citations') or 0,
        (it.get('title') or '')[:78], tail, ref)


def _rows(items, head='', total=None, a=None):
    """→ `{'text', 'structured'}`。带台账且 onlyNew 时先藏掉见过的。

    ⚠ **handler 必须返回 dict，不能返回字符串** —— 见踩坑 #150。
    """
    hidden = 0
    if a and a.get('session') and a.get('onlyNew'):
        items, hidden = litsearch.hide_seen(items)
    if hidden:
        head = (head + '\n' if head else '') + '（台账里见过的 %d 篇已隐去，只列新的）' % hidden
    text = (head + '\n' if head else '') + (
        '\n'.join(_line(it) for it in items) if items else '（没有结果）')
    st = {'count': len(items or []), 'items': items or [], 'hidden_seen': hidden}
    if total is not None:
        st['total_worldwide'] = total
    return {'text': text, 'structured': st}


def _search(a):
    items, total = litsearch.search(
        a.get('term') or '', limit=a.get('limit') or 25,
        year_from=a.get('yearFrom'), year_to=a.get('yearTo'), session=a.get('session'))
    head = '全世界命中 %d 篇，返回前 %d 篇。' % (total, len(items))
    if total > len(items):
        head += '（命中远多于返回时，说明检索词还可以再收窄）'
    return _rows(items, head, total=total, a=a)


def _semantic(a):
    items, info = litsearch.semantic(
        text=a.get('text') or '', like=_list(a.get('like')), unlike=_list(a.get('unlike')),
        year_from=a.get('yearFrom'), year_to=a.get('yearTo'),
        slice_by_year=bool(a.get('sliceByYear')), limit=a.get('limit') or 25,
        session=a.get('session'))
    wins = ', '.join('%s–%s' % (x or '…', y or '…') for x, y in info['windows'])
    head = ('按意思检索：发了 %d 次（年份窗口 %s），合并后 %d 篇，列前 %d 篇。'
            % (info['calls'], wins, info['pool'], len(items)))
    notes = ['语义检索每次最多 50 条、不按年份排序 —— 要新文章必须给年份；要更多开 sliceByYear']
    if not (a.get('yearFrom') or a.get('yearTo')):
        notes.append('⚠ 这次没给年份，结果里老文章会很多')
    if info['truncated']:
        notes.append('输入超过 1500 字，只用了前 1500 字')
    if info['exemplars_without_abstract']:
        notes.append('这些种子没摘要、只按标题找相似：' + ', '.join(info['exemplars_without_abstract']))
    if info['missing']:
        notes.append('这些种子在 OpenAlex 查不到，已跳过：' + ', '.join(info['missing']))
    notes.append('【无摘要】的文章（Elsevier 居多）只按标题匹配，语义检索对它们偏弱 —— 词面和引用两条腿别省')
    return _rows(items, head + '\n' + '\n'.join('· ' + n for n in notes), a=a)


def _abstract(a):
    it = litsearch.abstract(a.get('doi') or '')
    if not it:
        return {'text': '查不到这个 DOI（OpenAlex 里没有收录，或 DOI 写错了）。',
                'structured': {'found': False}}
    src = {'openalex': '', 'fulltext': '（来自证据库原文）', 's2': '（来自 Semantic Scholar）',
           'none': ''}.get(str(it.get('abstract_source') or ''), '')
    body = it.get('abstract') or '(源头没有摘要 —— Elsevier 的文章常见。只能凭标题判，判断时记 basis=title)'
    return {'text': '%s\n\n%s\n\n摘要%s：\n%s' % (it.get('title') or '(无标题)', _line(it), src, body),
            'structured': {'found': True, 'item': it}}


def _cited_by(a):
    items = litsearch.cited_by(a.get('doi') or '', a.get('limit') or 50, year_from=a.get('yearFrom'),
                               newest_first=bool(a.get('newestFirst')), session=a.get('session'))
    return _rows(items, a=a)


def _references(a):
    items = litsearch.references(a.get('doi') or '', a.get('limit') or 50,
                                 year_from=a.get('yearFrom'), session=a.get('session'))
    return _rows(items, a=a)


def _snowball(a):
    items, stats = litsearch.snowball_many(
        _list(a.get('dois')), direction=a.get('direction') or 'both',
        limit_per_seed=a.get('perSeed') or 50, year_from=a.get('yearFrom'),
        newest_first=bool(a.get('newestFirst')), limit=a.get('limit') or 100, session=a.get('session'))
    head = '种子 %d 篇：%s\n按「连到几个种子」排（多篇都引 / 都被它引的最该先看）。' % (
        len(stats), '；'.join('%s 后向%d 前向%d' % (d, b, f) for d, b, f, _n in stats))
    return _rows(items, head, a=a)


def _session_open(a):
    name = a.get('name') or ''
    if a.get('nextRound'):
        ledger.next_round(name)
    crit = _list(a.get('criteria')) if a.get('criteria') is not None else None
    s = ledger.open_session(name, question=a.get('question') or '', criteria=crit,
                            scope_note=a.get('scopeNote') or '')
    lines = ['台账「%s」· 第 %s 轮' % (s['name'], s['round']),
             '问题：%s' % (s.get('question') or '（还没写）'),
             '判据：%s' % ('；'.join('%d. %s' % (i + 1, c) for i, c in enumerate(s['criteria']))
                         or '（还没定 —— 和用户商量后用 criteria 写进来）')]
    if s.get('scope_notes'):
        lines.append('范围约定：' + '；'.join(n['note'] for n in s['scope_notes']))
    lines.append('已记 %d 次检索、%d 篇文献。' % (len(s['searches']), len(s['works'])))
    return {'text': '\n'.join(lines), 'structured': {k: s[k] for k in ('name', 'question', 'criteria',
                                                                      'scope_notes', 'round')}}


def _judge(a):
    js = a.get('judgments')
    if isinstance(js, str):
        try:
            js = json.loads(js)
        except ValueError:
            return {'text': 'judgments 不是合法的 JSON 数组', 'is_error': True}
    r = ledger.judge(a.get('session') or '', js or [])
    text = '记下 %d 条判断。' % r['judged']
    if r['unknown']:
        text += '\n台账里没有这些（先用带 session 的检索把它们记进来）：' + ', '.join(r['unknown'])
    if r['bad']:
        text += '\n这些的 verdict 认不出（只收 relevant/partial/irrelevant/unsure）：' + ', '.join(r['bad'])
    return {'text': text, 'structured': r}


def _status(a):
    st = ledger.status(a.get('session') or '', benchmark=_list(a.get('benchmark')) or None)
    v = st['verdicts']
    lines = ['台账「%s」· 第 %s 轮 · %d 次检索（外部请求 %d 次）· %d 篇'
             % (st['name'], st['round'], st['n_searches'], st['n_calls'], st['n_works']),
             '判断：相关 %d · 部分 %d · 不相关 %d · 没法判 %d · **还没判 %d**'
             % (v.get('relevant', 0), v.get('partial', 0), v.get('irrelevant', 0), v.get('unsure', 0),
                v.get('unjudged', 0)),
             '相关（含部分）%d 篇，其中只凭标题判的 %d 篇；全部文献里没摘要的 %d 篇'
             % (st['n_relevant'], st['relevant_title_only'], st['no_abstract']),
             '', '每轮新增（饱和曲线：连续一轮没有新的相关篇 = 饱和信号）：']
    for r in st['curve']:
        chs = '，'.join('%s 新%d/相关%d' % (c, x['new'], x['relevant']) for c, x in r['by_channel'].items())
        lines.append('  第 %d 轮：新 %d 篇，新的相关 %d 篇%s' % (r['round'], r['new_works'], r['new_relevant'],
                                                        ('（' + chs + '）') if chs else ''))
    if st['relevant_by_channel']:
        lines.append('各渠道找到的相关篇：' + '，'.join('%s %d' % kv for kv in st['relevant_by_channel'].items())
                     + '；只有它找到的：' + ('，'.join('%s %d' % kv for kv in st['relevant_only_by_channel'].items())
                                         or '无'))
    cr = st.get('capture_recapture')
    if cr:
        lines.append('捕获–再捕获（文本 %d × 引用 %d，重叠 %d）：估计相关总数约 %s，已找到约 %s%s'
                     % (cr['text'], cr['citation'], cr['both'], cr['estimated_total'],
                        '%.0f%%' % (100 * cr['estimated_coverage']) if cr['estimated_coverage'] else '?',
                        '' if cr['reliable'] else '（重叠太少，估计不可靠）'))
        lines.append('  ' + cr['note'])
    else:
        lines.append('捕获–再捕获：还算不了（要文本渠道和引用渠道都找到过相关篇）')
    rr = st.get('relative_recall')
    if rr:
        lines.append('相对召回：标准集 %d 篇，台账里出现 %d（%s），判为相关 %d（%s）'
                     % (rr['benchmark'], rr['found_anywhere'], rr['recall_found'], rr['judged_relevant'],
                        rr['recall_relevant']))
        if rr['missing']:
            lines.append('  没找到的：' + ', '.join(rr['missing'][:20]))
    return {'text': '\n'.join(lines), 'structured': st}


def _terms(a):
    m = ledger.mine_terms(a.get('session') or '', k=a.get('k') or 30)
    if not m['terms']:
        return {'text': '还挖不出新词：台账里判为相关的有 %d 篇（至少要几篇相关的，才能看出它们比其余多用了什么词）。'
                        % m['n_relevant'], 'structured': m}
    lines = ['从 %d 篇相关文献里挖出的说法（相对其余检索结果显著多出来的；已搜过的排除）：' % m['n_relevant']]
    if m['phrases']:
        lines.append('词组：')
        lines += ['  %-40s z=%-6s %d 篇' % (t['term'], t['z'], t['docs']) for t in m['phrases']]
    if m['words']:
        lines.append('单词（泛词多，组合进词组或 AND 里用）：' + '，'.join(
            '%s(%d)' % (t['term'], t['docs']) for t in m['words']))
    if m['authors']:
        lines.append('相关篇里反复出现的一作：' + '，'.join('%s（%d）' % x for x in m['authors']))
    if m['venues']:
        lines.append('相关篇集中的期刊：' + '，'.join('%s（%d）' % x for x in m['venues']))
    lines.append('用不用、怎么组合成下一轮检索式，由你决定。')
    return {'text': '\n'.join(lines), 'structured': m}


def register(server):
    """把本工具的 MCP 面挂到 server 上（聚合入口 host/mcp/server.py 会调这个）。"""

    server.register_tool(
        'lit_search',
        '**精确检索**全世界的文献：检索词必须真的出现在标题或摘要里（不是模糊相关性排序）。'
        '返回里带「这篇我库里有没有」，并告诉你全世界一共有多少篇 —— 命中数远大于返回数时，'
        '说明这个词还太宽，该收窄。免费额度内、只读。'
        '词组要加引号，多词用 AND，例：`"phenylboronic acid" AND siloxane`。'
        '**检索词控制在 3–5 个词**：它要求每个词都出现，7 个词以上基本搜不到（实测）。'
        '**换了说法的同一件事它搜不到** —— 配合 lit_semantic（按意思找）用。'
        '结果里标 [书/词条] 的是书章节、百科条目、学位论文；【无摘要】的只能凭标题判。'
        '⚠ 列表里的摘要是**预览**（截到 1500 字）；要完整判断一篇，用 lit_abstract。'
        '一次最多 200 条 —— 一个几十上百篇的领域可以一次捞干净。'
        '**用户的路线**：优先付费的好刊（Nature/Wiley/ACS/Elsevier/RSC 等），'
        'MDPI、Frontiers 这类只能当兜底、不能当默认 —— 每条结果都标了出版商和'
        '付费状态，照着挑。**付费 ≠ 拿不到**：用户有机构订阅，'
        'getpdf_one / paper_fulltext 能取到付费刊的全文，别因为 OA 方便就偏向它。',
        {'type': 'object', 'properties': dict(
            {'term': {'type': 'string', 'description': '检索词（支持引号词组与 AND）'}},
            **_YEARS, **_LIMIT, **_SESSION),
         'required': ['term']},
        _search)

    server.register_tool(
        'lit_semantic',
        '**按意思检索**全世界的文献（OpenAlex 向量检索，标题 + 摘要）：补 lit_search「换个说法就搜不到」的盲区。'
        '两种用法：text = 一段话描述要找什么（英文，一段话比几个词好）；'
        'like = 几篇已判相关的 DOI，「照着它们找相似的」（每篇单独搜再融合，你不用搬摘要）；'
        'unlike = 几篇不要的，跟它们像的往后排。'
        '⚠ 每次最多 50 条、**不按年份排序** —— 找新进展必须给 yearFrom；要更多开 sliceByYear（按年切片，每片 50 条）。'
        '【无摘要】的文章（Elsevier 居多）只按标题匹配，它对这些偏弱，所以词面和引用两条腿别省。'
        '每次 $0.001（免费额度约 1000 次/天），一次调用最多发 8 次（输入条数 × 年份片数）。只读。',
        {'type': 'object', 'properties': dict(
            {'text': {'type': 'string', 'description': '一段话（英文）：要找什么样的工作'},
             'like': {'type': 'array', 'items': {'type': 'string'},
                      'description': '照着这几篇找（DOI，≤5）'},
             'unlike': {'type': 'array', 'items': {'type': 'string'},
                        'description': '别要像这几篇的（DOI，≤3）'},
             'sliceByYear': {'type': 'boolean',
                             'description': '按年切片分别检索（≤6 片），突破每次 50 条；需要 yearFrom'}},
            **_YEARS, **_LIMIT, **_SESSION)},
        _semantic)

    server.register_tool(
        'lit_abstract',
        '按 DOI 取一篇的**完整摘要（不截断）**。判断一篇贴不贴题、有没有你要的配方，'
        '靠读摘要，不要看标题猜 —— 关键的方法描述常常在摘要靠后的位置，'
        'lit_search 列表里的预览可能正好把它切掉。OpenAlex 没摘要时回退到证据库原文、Semantic Scholar；'
        '都没有就明说（Elsevier 常见），这时判断记 basis=title。只读。',
        {'type': 'object', 'properties': dict(_DOI), 'required': ['doi']},
        _abstract)

    server.register_tool(
        'lit_cited_by',
        '谁引用了这篇（**前向雪球**）—— 用来看「这个方向后来怎么发展的」。'
        '默认按被引排；找最新进展用 newestFirst=true + yearFrom（否则刚发表的新工作会被压到最后）。'
        '多篇一起做用 lit_snowball。只读。',
        {'type': 'object', 'properties': dict(
            _DOI, **_LIMIT, **_SESSION,
            yearFrom={'type': 'integer', 'description': '只要这一年及以后的'},
            newestFirst={'type': 'boolean', 'description': '按年份新到旧排'}),
         'required': ['doi']},
        _cited_by)

    server.register_tool(
        'lit_references',
        '这篇引用了谁（**后向雪球**）—— 用来看「这个方向的根在哪」。多篇一起做用 lit_snowball。只读。',
        {'type': 'object', 'properties': dict(
            _DOI, **_LIMIT, **_SESSION,
            yearFrom={'type': 'integer', 'description': '只要这一年及以后的'}),
         'required': ['doi']},
        _references)

    server.register_tool(
        'lit_snowball',
        '**一次对多篇做雪球**（≤10 篇种子），结果按「连到几个种子」排 —— 几篇相关文章都引、或都被它引的最该先看。'
        '用法：每轮挑 2–5 篇最好的相关篇当种子。direction = forward（谁引了它们）/ backward（它们引了谁）/ both。'
        '找最新进展用 newestFirst=true + yearFrom。只读。',
        {'type': 'object', 'properties': dict(
            {'dois': {'type': 'array', 'items': {'type': 'string'}, 'description': '种子 DOI（≤10）'},
             'direction': {'type': 'string', 'enum': ['forward', 'backward', 'both']},
             'perSeed': {'type': 'integer', 'minimum': 1, 'maximum': 200,
                         'description': '每篇种子每个方向最多取多少条，默认 50'},
             'yearFrom': {'type': 'integer', 'description': '只要这一年及以后的'},
             'newestFirst': {'type': 'boolean', 'description': '前向按年份新到旧取'}},
            **_LIMIT, **_SESSION),
         'required': ['dois']},
        _snowball)

    server.register_tool(
        'lit_session',
        '建 / 读 / 更新一个**检索台账**（一个研究问题一个）。多轮全面检索的起点：'
        '先和用户商定「相关」要满足哪几条（criteria，拆成小条，例：["剪切硬化或率相关硬化", "用了动态键", "2023 年后"]），'
        '范围上的约定（scopeNote，例：「应用类不算」「综述单列」）原话写进来，后续轮次照着办。'
        'nextRound=true 进入下一轮。之后所有检索带上 session=这个名字。只写本地台账文件。',
        {'type': 'object', 'properties': {
            'name': {'type': 'string', 'description': '台账名（英文/中文都行，同一个问题始终用同一个）'},
            'question': {'type': 'string', 'description': '用户的问题原话'},
            'criteria': {'type': 'array', 'items': {'type': 'string'},
                         'description': '判据（给了就替换原来的）'},
            'scopeNote': {'type': 'string', 'description': '追加一条范围约定'},
            'nextRound': {'type': 'boolean', 'description': '进入下一轮'}},
         'required': ['name']},
        _session_open)

    server.register_tool(
        'lit_judge',
        '把你对一批文献的判断记进台账（一次多篇）。每条：'
        '{"doi": "...", "verdict": "relevant|partial|irrelevant|unsure", '
        '"criteria": {"判据1": "yes|partial|no|unknown", ...}, "basis": "abstract|title|fulltext", "reason": "一句话"}。'
        '**按判据逐条判**比整体判更准；只看了标题的 basis 写 title（统计里单列，不当确定）。'
        '没 DOI 的用结果里给的 title: 键。只写本地台账文件。',
        {'type': 'object', 'properties': {
            'session': {'type': 'string', 'description': '台账名'},
            'judgments': {'type': 'array', 'items': {'type': 'object'}, 'description': '判断列表'}},
         'required': ['session', 'judgments']},
        _judge)

    server.register_tool(
        'lit_status',
        '看台账：每轮每个渠道新增了多少篇、多少篇相关（**饱和曲线**：连续一轮三个渠道都没有新的相关篇 = 该停了）；'
        '各渠道各自独有的贡献；文本渠道对引用渠道的**捕获–再捕获估计**（还漏多少，只当参考）；'
        '还有多少没判、多少只凭标题判。给 benchmark（一组 DOI，如某篇综述的参考文献）还会算相对召回。只读。',
        {'type': 'object', 'properties': {
            'session': {'type': 'string', 'description': '台账名'},
            'benchmark': {'type': 'array', 'items': {'type': 'string'},
                          'description': '标准集 DOI（可选）'}},
         'required': ['session']},
        _status)

    server.register_tool(
        'lit_terms',
        '从台账里**判为相关的文献**挖出新说法：相对其余检索结果显著多出来的词组（纯统计，不预设词表，已搜过的排除），'
        '外加相关篇里反复出现的一作与期刊。下一轮的检索词优先从这里取 —— 真实文献里的说法比凭空想的全。只读。',
        {'type': 'object', 'properties': {
            'session': {'type': 'string', 'description': '台账名'},
            'k': {'type': 'integer', 'minimum': 5, 'maximum': 80, 'description': '最多列多少个词组，默认 30'}},
         'required': ['session']},
        _terms)
