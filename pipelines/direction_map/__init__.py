# -*- coding: utf-8 -*-
"""direction_map · 方向地图（编排：一批种子论文 → 这个领域长什么样）

回答「**这个方向过去/现在是什么形势**」：谁做了什么、用了什么方法、
实现了什么性能、用在哪 —— 而不是「某一篇讲了什么」。

## 四步，每步单独可跑

```
1  seeds     三路取种子 → seed_pool
             ① OpenAlex 检索（工程侧的唯一来源）
             ② 已有窄带的语料（公众号 = 化学侧）
             ③ 用户 Zotero 库（本人在读的）
2  build     seed_pool → OpenAlex 取元数据 + 参考文献 → works / edges
3  cluster   文献耦合 + Louvain                     → clusters
4  report    人读的地图 / 导出
```

拆开的理由是成本不同：`build` 是几百次网络请求要十几分钟，
`cluster` / `report` 是纯本地的、可以反复调参重跑。

## ⚠ 一切都按「窄带」分库

`core.paths.direction_db(band)`，band 是必填、没有默认值。
用户会陆续做多条窄带，**加一条窄带必须是「加一份 band.json」而不是「改代码」**。
留默认值就会有人忘了传，然后两条窄带的数据混进同一个库。

## 为什么种子必须三路取（实测，不是设计洁癖）

拿「高分子抗冲」实测：现有 754 篇公众号种子里抗冲相关 94 篇，
但**散在 8 个以上的簇里，没有任何一个簇是「抗冲」**；
而「剪切增稠 / 硬化」只命中 2 篇、「防护装备」只命中 3 篇。

**公众号只覆盖化学半边（强韧/自修复/动态键弹性体，发 AM/AFM/JACS），
工程半边零覆盖**（聚脲防爆、弹道防护、剪切增稠，发 IJIE / Composite Structures）。
只用公众号会得到一张缺一半的图。

## 实测规模（wechat_polymer 窄带，835 篇推送）

    种子 754 篇（DOI 对齐率 98.2%）· 唯一参考文献 39218 · 引用边 55418
    骨干（被 >=3 篇种子共引）2934 篇   ← 只给骨干拉元数据
    聚类 res=3.0 → 36 个簇，主题纯度 0.48

**为什么只给骨干拉元数据**：39218 篇要 1000 次请求，而其中 90% 只被一篇种子引用
（各自的背景引用），对「领域长什么样」没有贡献。门槛卡 df>=3，量降到 1/13。

依赖：adapters.wechat_seed / adapters.openalex / adapters.zotero_client /
domain.bibliometrics / core。本环**不联网**（联网都在 adapters 里）。
"""
import collections
import io
import json
import os
import re
import sqlite3
import time

from core import errors, paths
from core.log import get_logger
from adapters import openalex, wechat_seed
from domain import bibliometrics as bib

log = get_logger('direction_map')

SEED_SELECT = ('id,doi,title,publication_year,publication_date,cited_by_count,'
               'referenced_works,topics,primary_location')
REF_SELECT = 'id,doi,title,publication_year,cited_by_count,primary_location'

SCHEMA = """
CREATE TABLE IF NOT EXISTS works (
    id TEXT PRIMARY KEY, doi TEXT, title TEXT, year INTEGER,
    venue TEXT, cited_by INTEGER, topic TEXT,
    is_seed INTEGER DEFAULT 0, wx_date TEXT);
CREATE TABLE IF NOT EXISTS edges (src TEXT, dst TEXT, PRIMARY KEY (src, dst));
CREATE TABLE IF NOT EXISTS seed_pool (
    work_id TEXT PRIMARY KEY, doi TEXT, source TEXT, detail TEXT, added TEXT);
CREATE TABLE IF NOT EXISTS wechat_files (
    file TEXT PRIMARY KEY, doi TEXT, pubdate TEXT, work_id TEXT);
CREATE TABLE IF NOT EXISTS clusters (
    work_id TEXT, cluster INTEGER, resolution REAL, PRIMARY KEY (work_id));
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
CREATE INDEX IF NOT EXISTS idx_works_seed ON works(is_seed);
CREATE INDEX IF NOT EXISTS idx_seed_source ON seed_pool(source);
"""


class DirectionMapError(errors.PlatformError):
    """方向地图流程失败。"""


def _conn(band):
    paths.direction_dir(band, create=True)
    c = sqlite3.connect(paths.direction_db(band))
    c.executescript(SCHEMA)
    return c


def _venue(w):
    return (((w.get('primary_location') or {}).get('source') or {})
            .get('display_name') or '')


def _topic(w):
    t = (w.get('topics') or [])
    return (t[0].get('display_name') or '') if t else ''


def _short(wid):
    return (wid or '').rsplit('/', 1)[-1]


def _now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


# ══════════════════════════════════════════════════════════════════════
# 窄带定义
# ══════════════════════════════════════════════════════════════════════
def load_spec(band):
    """读窄带定义。没有就抛错 —— 定义是窄带的第一等公民，不该有隐式默认。"""
    p = paths.direction_spec(band)
    if not os.path.exists(p):
        raise DirectionMapError(
            '窄带「%s」还没有定义文件：%s\n'
            '先写一份 band.json（例子见 pipelines/direction_map/CLAUDE.md）' % (band, p))
    return json.load(io.open(p, encoding='utf-8'))


def save_spec(band, spec):
    """写窄带定义。加一条窄带 = 加一份这个文件。"""
    paths.direction_dir(band, create=True)
    io.open(paths.direction_spec(band), 'w', encoding='utf-8').write(
        json.dumps(spec, ensure_ascii=False, indent=1))
    return paths.direction_spec(band)


# ══════════════════════════════════════════════════════════════════════
# 第一步：三路取种子
# ══════════════════════════════════════════════════════════════════════
def _add_seeds(c, rows):
    """rows: [(work_id, doi, source, detail)]。返回新增数（已有的不覆盖来源）。"""
    before = c.execute('SELECT COUNT(*) FROM seed_pool').fetchone()[0]
    c.executemany('INSERT OR IGNORE INTO seed_pool VALUES (?,?,?,?,?)',
                  [(w, d, s, t, _now()) for w, d, s, t in rows])
    return c.execute('SELECT COUNT(*) FROM seed_pool').fetchone()[0] - before


def seeds_from_openalex(band, spec=None, progress=None):
    """① 按 band.json 里的检索式取种子。**工程侧文献的唯一来源。**"""
    say = progress or (lambda *a: None)
    spec = spec or load_spec(band)
    c = _conn(band)
    total_new = 0
    try:
        for q in spec.get('queries', []):
            text = q['q']
            limit = int(q.get('limit', 100))
            items, tot = openalex.search(text, limit=limit, year_from=q.get('year_from'))
            got = []
            for it in items:
                wid = _short(it.get('openalex_id') or '')
                if wid:
                    got.append((wid, wechat_seed.normalize_doi(it.get('doi')),
                                'openalex', text))
            with c:
                n = _add_seeds(c, got)
            total_new += n
            say('  [OpenAlex] %-44s 命中 %-9s 取 %3d 新增 %3d'
                % (text[:44], '{:,}'.format(tot), len(got), n))
    finally:
        c.close()
    return total_new


def seeds_from_band(band, spec=None, progress=None):
    """② 从已有窄带的语料里挑（公众号 = 化学侧）。不联网。"""
    say = progress or (lambda *a: None)
    spec = spec or load_spec(band)
    src = spec.get('from_band')
    if not src:
        say('  [已有窄带] band.json 里没配 from_band，跳过')
        return 0
    if not os.path.exists(paths.direction_db(src['band'])):
        say('  [已有窄带] 源窄带「%s」还没建库，跳过' % src['band'])
        return 0
    pat = re.compile(src.get('match', '.'), re.I)
    s = sqlite3.connect(paths.direction_db(src['band']))
    hits = [(r[0], r[1] or '') for r in
            s.execute('SELECT id,doi,title FROM works WHERE is_seed=1')
            if pat.search(r[2] or '')]
    s.close()
    c = _conn(band)
    try:
        with c:
            n = _add_seeds(c, [(w, d, 'band:' + src['band'], src.get('match', '')[:60])
                               for w, d in hits])
    finally:
        c.close()
    say('  [已有窄带] %s 里匹配 %d 篇，新增 %d' % (src['band'], len(hits), n))
    return n


def seeds_from_zotero(band, spec=None, progress=None):
    """③ 用户自己的 Zotero 库。**只能在 Zotero 在跑的那台机器上取**（本地 API）。

    取不到不是错误 —— 编程端本来就没有真实库。跳过并说明即可。
    """
    say = progress or (lambda *a: None)
    spec = spec or load_spec(band)
    conf = spec.get('zotero')
    if not conf:
        say('  [Zotero] band.json 里没配 zotero，跳过')
        return 0
    try:
        from adapters import zotero_client
        items = zotero_client.search_items(conf.get('query', ''),
                                           limit=int(conf.get('limit', 300)),
                                           qmode=conf.get('qmode', 'everything'),
                                           tag=conf.get('tag'),
                                           collection=conf.get('collection'))
        dois = zotero_client.dois_of(items)
    except Exception as e:
        say('  [Zotero] 取不到（多半是本机没跑 Zotero）：%s' % str(e)[:80])
        return 0
    if not dois:
        say('  [Zotero] 匹配到 %d 条但都没有 DOI，跳过（编程端是测试账号，属正常）'
            % len(items))
        return 0
    works = openalex.works_by_dois(dois, select='id,doi')
    c = _conn(band)
    try:
        with c:
            n = _add_seeds(c, [(w, wechat_seed.normalize_doi(x.get('doi')),
                                'zotero', str(conf.get('query', ''))[:60])
                               for w, x in works.items()])
    finally:
        c.close()
    say('  [Zotero] %d 条有 DOI，对齐 %d 篇，新增 %d' % (len(dois), len(works), n))
    return n


def seeds_from_wechat(band, seed_dir, progress=None):
    """④（可选）直接从公众号 md 目录取。用于建 wechat_polymer 那类窄带。"""
    say = progress or (lambda *a: None)
    seeds = wechat_seed.scan(seed_dir)
    st = wechat_seed.stats(seeds)
    say('  [公众号] %d 篇 | 有 DOI %d（%.1f%%）| %s ~ %s'
        % (st['total'], st['with_doi'], 100 * st['doi_rate'], st['earliest'], st['latest']))
    dois = sorted(set(s['doi'] for s in seeds if s['doi']))
    works = openalex.works_by_dois(dois, select='id,doi')
    doi2wid = {wechat_seed.normalize_doi(w.get('doi')): k for k, w in works.items()}
    c = _conn(band)
    try:
        with c:
            n = _add_seeds(c, [(k, wechat_seed.normalize_doi(w.get('doi')),
                                'wechat', os.path.basename(seed_dir))
                               for k, w in works.items()])
            c.executemany('INSERT OR REPLACE INTO wechat_files VALUES (?,?,?,?)',
                          [(s['file'], s['doi'], s['pubdate'],
                            doi2wid.get(s['doi'], '')) for s in seeds])
    finally:
        c.close()
    say('  [公众号] 对齐 %d / %d 个 DOI，新增 %d' % (len(works), len(dois), n))
    return n


def collect_seeds(band, progress=None):
    """三路取种子，落进 seed_pool。返回各来源的新增数。"""
    say = progress or (lambda *a: None)
    spec = load_spec(band)
    say('窄带「%s」· %s' % (band, spec.get('name', '')))
    out = {'openalex': seeds_from_openalex(band, spec, say),
           'band': seeds_from_band(band, spec, say),
           'zotero': seeds_from_zotero(band, spec, say)}
    c = _conn(band)
    tot = c.execute('SELECT COUNT(*) FROM seed_pool').fetchone()[0]
    by = dict(c.execute('SELECT source,COUNT(*) FROM seed_pool GROUP BY source'))
    c.close()
    say('')
    say('seed_pool 共 %d 篇：%s'
        % (tot, ' · '.join('%s %d' % kv for kv in sorted(by.items()))))
    out['total'] = tot
    return out


# ══════════════════════════════════════════════════════════════════════
# 第二步：建图
# ══════════════════════════════════════════════════════════════════════
def ref_rows_for(refs_meta, seed_ids):
    """骨干参考文献 → works 表的行；**跳过本身就是种子的那些**。返回 (行, 跳过数)。

    ⚠ 这个函数存在的唯一原因是一个实测踩过的坑（踩坑 #75）：
    种子和参考文献会重叠 —— 一篇种子被其他种子引 >=min_df 次，就同时出现在两边。
    `works` 以 id 为主键，照插的话后写的 `is_seed=0` 会把种子标记覆盖掉。
    **实测被这样降级的有 120 篇，而且恰恰是被同行引得最多的那 120 篇** ——
    这个领域最重要的论文全被踢出了聚类（矩阵只剩 634 而不是 754）。

    失败形式很隐蔽：不报错、不缺数据，只是聚类的输入悄悄少了最核心的一批。
    抽成独立函数就是为了能离线测它。
    """
    rows, overlap = [], 0
    for wid, w in refs_meta.items():
        if wid in seed_ids:
            overlap += 1
            continue
        rows.append((wid, wechat_seed.normalize_doi(w.get('doi')), w.get('title') or '',
                     w.get('publication_year'), _venue(w),
                     w.get('cited_by_count') or 0, '', 0, ''))
    return rows, overlap


def build(band, min_df=3, progress=None):
    """读 seed_pool → 取元数据与参考文献 → works / edges。可重复运行（幂等）。"""
    say = progress or (lambda *a: None)
    c = _conn(band)
    pool = [r[0] for r in c.execute('SELECT work_id FROM seed_pool')]
    wxdate = dict((r[0], r[1]) for r in
                  c.execute("SELECT work_id,pubdate FROM wechat_files WHERE work_id<>''"))
    c.close()
    if not pool:
        raise DirectionMapError('seed_pool 是空的，先跑 collect_seeds()')
    say('[1/3] seed_pool %d 篇，取元数据与参考文献...' % len(pool))

    works = openalex.works_by_ids(
        pool, select=SEED_SELECT,
        on_progress=lambda d, t, f: say('      ...%d/%d → %d' % (d, t, f))
                    if d % 400 == 0 else None)
    say('[1/3] 取到 %d / %d' % (len(works), len(pool)))

    refsets, rows, edge_rows = {}, [], []
    for wid, w in works.items():
        refs = set(_short(r) for r in (w.get('referenced_works') or []))
        refsets[wid] = refs
        rows.append((wid, wechat_seed.normalize_doi(w.get('doi')), w.get('title') or '',
                     w.get('publication_year'), _venue(w), w.get('cited_by_count') or 0,
                     _topic(w), 1, wxdate.get(wid, '')))
        edge_rows.extend((wid, r) for r in refs)

    counts = bib.shared_counts(refsets)
    backbone = [r for r, n in counts.items() if n >= min_df]
    say('[2/3] 唯一参考文献 %d | 引用边 %d | 骨干(被>=%d篇共引) %d，拉元数据...'
        % (len(counts), len(edge_rows), min_df, len(backbone)))
    refs_meta = openalex.works_by_ids(
        backbone, select=REF_SELECT,
        on_progress=lambda d, t, f: say('      ...%d/%d → %d' % (d, t, f))
                    if d % 800 == 0 else None)
    ref_rows, overlap = ref_rows_for(refs_meta, set(works))
    rows.extend(ref_rows)
    if overlap:
        say('      其中 %d 篇骨干本身就是种子，保留种子身份（不降级）' % overlap)

    say('[3/3] 落库 %s' % paths.direction_db(band))
    c = _conn(band)
    with c:
        c.executemany('INSERT OR REPLACE INTO works VALUES (?,?,?,?,?,?,?,?,?)', rows)
        c.executemany('INSERT OR IGNORE INTO edges VALUES (?,?)', edge_rows)
        c.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',
                  ('build', json.dumps({'band': band, 'min_df': min_df,
                                        'seeds': len(works), 'refs': len(counts),
                                        'edges': len(edge_rows), 'at': _now()},
                                       ensure_ascii=False)))
    c.close()
    log.info('build[%s] 种子 %d / 参考文献 %d / 边 %d'
             % (band, len(works), len(counts), len(edge_rows)))
    return {'seeds': len(works), 'refs': len(counts),
            'edges': len(edge_rows), 'backbone': len(refs_meta)}


# ══════════════════════════════════════════════════════════════════════
# 第三步：聚类
# ══════════════════════════════════════════════════════════════════════
def _load(c):
    seeds = {}
    for wid, title, year, venue, cited, topic, wx in c.execute(
            'SELECT id,title,year,venue,cited_by,topic,wx_date FROM works WHERE is_seed=1'):
        seeds[wid] = {'title': title, 'year': year, 'venue': venue,
                      'cited': cited, 'topic': topic, 'wx_date': wx}
    refsets = collections.defaultdict(set)
    for src, dst in c.execute('SELECT src,dst FROM edges'):
        refsets[src].add(dst)
    titles = dict(c.execute('SELECT id,title FROM works WHERE is_seed=0'))
    return seeds, refsets, titles


def cluster(band, resolutions=(1.5, 2.0, 2.5, 3.0), min_size=5, tries=10, progress=None):
    """从库里读出来聚类，结果写回 clusters 表。返回扫描报告。"""
    say = progress or (lambda *a: None)
    c = _conn(band)
    seeds, refsets, titles = _load(c)
    if not seeds:
        c.close()
        raise DirectionMapError('库里没有种子，先跑 collect_seeds() + build()')

    tools = bib.tool_refs(titles)
    say('通用工具类参考文献 %d 条（不参与相似度，保留在地基）' % len(tools))

    keys = sorted(seeds)
    keys, S = bib.coupling_matrix(refsets, exclude=tools, keys=keys)
    say('相似度矩阵 %d×%d，非零边 %d' % (len(keys), len(keys), int((S > 0).sum() / 2)))

    labels, report_ = bib.best_partition(
        S, keys, lambda k: seeds[k]['topic'] or '?',
        resolutions=resolutions, tries=tries, min_size=min_size)
    for res, q, ncl, cov, p in report_:
        say('  res=%.1f | 模块度 %.3f | 簇>=%d %2d | 覆盖 %d/%d | 主题纯度 %.2f'
            % (res, q, min_size, ncl, cov, len(keys), p))
    best_res = max(report_, key=lambda r: r[4])[0]
    say('选定 res=%.1f（按主题纯度，不按模块度 —— 见 domain.bibliometrics 说明）' % best_res)

    with c:
        c.execute('DELETE FROM clusters')
        c.executemany('INSERT OR REPLACE INTO clusters VALUES (?,?,?)',
                      [(k, int(l), best_res) for k, l in zip(keys, labels)])
        c.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',
                  ('cluster', json.dumps({'resolution': best_res, 'report': report_},
                                         ensure_ascii=False)))
    c.close()
    log.info('cluster[%s] res=%.1f，%d 个节点' % (band, best_res, len(keys)))
    return report_


# ══════════════════════════════════════════════════════════════════════
# 第四步：报告
# ══════════════════════════════════════════════════════════════════════
def report(band, min_size=5, top_refs=4, out=None):
    """生成人读的方向地图。返回字符串；给 out 就同时写文件。"""
    c = _conn(band)
    seeds, refsets, titles = _load(c)
    meta = dict(c.execute('SELECT k,v FROM meta'))
    ref_info = {wid: (t, y, v) for wid, t, y, v in c.execute(
        'SELECT id,title,year,venue FROM works WHERE is_seed=0')}
    lab = dict((w, cl) for w, cl, _ in c.execute('SELECT * FROM clusters'))
    c.close()
    if not lab:
        raise DirectionMapError('还没聚类，先跑 cluster()')

    tools = bib.tool_refs(titles)
    groups = bib.groups_of(list(lab), [lab[k] for k in lab], min_size=min_size)
    all_periods = sorted(set(x for x in (bib.half_year(seeds[k]['wx_date'])
                                         for k in seeds) if x))

    L = []
    b = json.loads(meta.get('build', '{}'))
    L.append('方向地图「%s」· 种子 %s 篇 / 参考文献 %s 篇 / 引用边 %s 条'
             % (band, b.get('seeds', '?'), b.get('refs', '?'), b.get('edges', '?')))
    L.append('分辨率 %s · %d 个簇（>=%d 篇）'
             % (json.loads(meta.get('cluster', '{}')).get('resolution', '?'),
                len(groups), min_size))
    if all_periods:
        L.append('⚠ 最后一个时间段可能不满半年，别直接拿它比出「在下降」')
    L.append('')

    for gi, mem in enumerate(groups, 1):
        topic = collections.Counter(seeds[k]['topic'] or '?'
                                    for k in mem).most_common(1)[0][0]
        head = '--- 簇%-2d | %3d 篇 | %s' % (gi, len(mem), topic[:46])
        if all_periods:
            _cnt, series = bib.trend([seeds[k]['wx_date'] for k in mem], all_periods)
            L.append(head + '  ' + bib.direction(series))
            L.append('    趋势 ' + '  '.join('%s:%d' % (p, n)
                                            for p, n in zip(all_periods, series)))
        else:
            L.append(head)
        shared = collections.Counter()
        for k in mem:
            shared.update(refsets.get(k) or ())
        shown = 0
        for r, n in shared.most_common(200):
            if n < 2 or r not in ref_info:
                continue
            t, y, v = ref_info[r]
            L.append('    地基 [%2d/%d] %s %-26s %s%s'
                     % (n, len(mem), y, (v or '?')[:26], (t or '')[:56],
                        ' [工具]' if r in tools else ''))
            shown += 1
            if shown >= top_refs:
                break
        L.append('')

    L.append('=== 全域地基（被最多种子共同引用）===')
    for r, n in bib.top_shared(refsets, min_df=1)[:30]:
        if r not in ref_info:
            continue
        t, y, v = ref_info[r]
        L.append('  [%2d] %s %-30s %s%s' % (n, y, (v or '?')[:30], (t or '')[:60],
                                            ' [工具]' if r in tools else ''))
    text = '\n'.join(L)
    if out:
        io.open(out, 'w', encoding='utf-8').write(text)
    return text


def stats(band):
    """库里现在有什么。体检和面板用。"""
    if not os.path.exists(paths.direction_db(band)):
        return {'exists': False, 'band': band}
    c = _conn(band)
    g = lambda q: c.execute(q).fetchone()[0]
    s = {'exists': True, 'band': band,
         'seed_pool': g('SELECT COUNT(*) FROM seed_pool'),
         'by_source': dict(c.execute(
             'SELECT source,COUNT(*) FROM seed_pool GROUP BY source')),
         'seeds': g('SELECT COUNT(*) FROM works WHERE is_seed=1'),
         'refs': g('SELECT COUNT(*) FROM works WHERE is_seed=0'),
         'edges': g('SELECT COUNT(*) FROM edges'),
         'clustered': g('SELECT COUNT(*) FROM clusters'),
         'meta': dict(c.execute('SELECT k,v FROM meta'))}
    c.close()
    return s
