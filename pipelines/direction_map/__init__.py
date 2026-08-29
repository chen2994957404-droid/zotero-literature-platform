# -*- coding: utf-8 -*-
"""direction_map · 方向地图（编排：一批种子论文 → 这个领域长什么样）

回答的是「我的方向过去/现在是什么形势」，而不是「某一篇讲了什么」。

## 流水线

    公众号 md 目录
      → adapters.wechat_seed      提 DOI + 推送日期（正文提完即弃）
      → adapters.openalex         DOI 对齐 + 拉参考文献（批量，免费无密钥）
      → SQLite (core.paths)       works / edges / seeds / clusters
      → domain.bibliometrics      文献耦合 + Louvain + 时间趋势
      → 报告

**分三步、每步单独可跑**，因为拉引用网络是几百次网络请求、要几十分钟：
`build()` 落库之后，`cluster()` 和 `report()` 都是纯本地的，可以反复调参重跑。

## 实测规模（835 篇公众号推送，2025-01 ~ 2026-08）

    种子 754 篇（DOI 对齐率 98.2%）
    唯一参考文献 39218 篇 / 引用边 55418 条
    骨干（被 >=3 篇种子共引）2934 篇   ← 只给骨干拉元数据，不给全部 39218 篇拉
    聚类 res=3.0 → 36 个簇，主题纯度 0.48

**为什么只给骨干拉元数据**：39218 篇要 1000 次请求、半小时以上，而其中 90%
只被一篇种子引用（各自的背景引用），对「领域长什么样」没有贡献。
门槛卡在 df>=3，元数据量降到 1/13，信息几乎不损失。

对外接口：
    build(seed_dir, min_df=3, progress=print)   → 抓取 + 落库，返回统计
    cluster(resolutions=..., min_size=5)        → 聚类 + 落库，返回报告
    report(limit=None)                          → 生成人读的方向地图文本
    stats()                                     → 当前库里有什么

依赖：adapters.wechat_seed / adapters.openalex / domain.bibliometrics / core。
本环**不联网**（联网都在 adapters 里）。
"""
import collections
import io
import json
import os
import sqlite3

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
CREATE TABLE IF NOT EXISTS seeds (
    file TEXT PRIMARY KEY, doi TEXT, pubdate TEXT, work_id TEXT);
CREATE TABLE IF NOT EXISTS clusters (
    work_id TEXT, cluster INTEGER, resolution REAL, PRIMARY KEY (work_id));
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
CREATE INDEX IF NOT EXISTS idx_works_seed ON works(is_seed);
"""


class DirectionMapError(errors.PlatformError):
    """方向地图流程失败。"""


def _conn():
    os.makedirs(paths.DIRECTION, exist_ok=True)
    c = sqlite3.connect(paths.direction_db())
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


def ref_rows_for(refs_meta, seed_ids):
    """骨干参考文献 → works 表的行；**跳过本身就是种子的那些**。返回 (行, 跳过数)。

    ⚠ 这个函数存在的唯一原因是一个实测踩过的坑：
    种子和参考文献会重叠 —— 一篇种子被其他种子引 >=min_df 次，就同时出现在两边。
    `works` 以 id 为主键，照插的话后写的 `is_seed=0` 会把种子标记覆盖掉。
    **实测被这样降级的有 120 篇，而且恰恰是被同行引得最多的那 120 篇** ——
    这个领域最重要的论文全被踢出了聚类（矩阵只剩 634 而不是 754）。

    失败形式很隐蔽：不报错、不缺数据，只是聚类的输入悄悄少了一批，
    而少掉的是最核心的一批。抽成独立函数就是为了能离线测它。

    重叠时保留种子那一行：它的信息更全（有 topics、referenced_works、推送日期）。
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


# ══════════════════════════════════════════════════════════════════════
# 第一步：抓取 + 落库
# ══════════════════════════════════════════════════════════════════════
def build(seed_dir, min_df=3, progress=None):
    """扫种子目录 → 对齐 OpenAlex → 拉骨干参考文献 → 全部落进 SQLite。

    可重复运行：同一个 seed_dir 再跑一次是幂等的（主键覆盖）。
    """
    say = progress or (lambda *a: None)
    seeds = wechat_seed.scan(seed_dir)
    st = wechat_seed.stats(seeds)
    say('[1/4] 种子目录 %d 篇 | 有 DOI %d（%.1f%%）| 去重 %d | %s ~ %s' % (
        st['total'], st['with_doi'], 100 * st['doi_rate'],
        st['unique_doi'], st['earliest'], st['latest']))

    dois = sorted(set(s['doi'] for s in seeds if s['doi']))
    if not dois:
        raise DirectionMapError('一个 DOI 都没提到，检查下载的是不是 md 格式')

    say('[2/4] 对齐 OpenAlex（%d 个 DOI）...' % len(dois))
    works = openalex.works_by_dois(
        dois, select=SEED_SELECT,
        on_progress=lambda d, t, f: say('      ...%d/%d → 命中 %d' % (d, t, f))
                    if d % 200 == 0 else None)
    say('[2/4] 命中 %d / %d 个 DOI（%.1f%%），占全部文章 %.1f%%' % (
        len(works), len(dois), 100.0 * len(works) / len(dois),
        100.0 * len(works) / st['total']))

    # 公众号推送日期：按 DOI 挂回去（论文发表年 ≠ 何时被这个圈子关注）
    doi2date = {}
    for s in seeds:
        if s['doi'] and s['pubdate']:
            doi2date.setdefault(s['doi'], s['pubdate'])

    refsets = {}
    rows, edge_rows = [], []
    for wid, w in works.items():
        doi = wechat_seed.normalize_doi(w.get('doi'))
        refs = set(_short(r) for r in (w.get('referenced_works') or []))
        refsets[wid] = refs
        rows.append((wid, doi, w.get('title') or '', w.get('publication_year'),
                     _venue(w), w.get('cited_by_count') or 0, _topic(w),
                     1, doi2date.get(doi, '')))
        edge_rows.extend((wid, r) for r in refs)

    counts = bib.shared_counts(refsets)
    backbone = [r for r, n in counts.items() if n >= min_df]
    say('[3/4] 唯一参考文献 %d | 引用边 %d | 骨干(被>=%d篇共引) %d，拉元数据...' % (
        len(counts), len(edge_rows), min_df, len(backbone)))
    refs_meta = openalex.works_by_ids(
        backbone, select=REF_SELECT,
        on_progress=lambda d, t, f: say('      ...%d/%d → %d' % (d, t, f))
                    if d % 800 == 0 else None)
    ref_rows, overlap = ref_rows_for(refs_meta, set(works))
    rows.extend(ref_rows)
    if overlap:
        say('      其中 %d 篇骨干本身就是种子，保留种子身份（不降级）' % overlap)

    say('[4/4] 落库 %s' % paths.direction_db())
    c = _conn()
    with c:
        c.executemany('INSERT OR REPLACE INTO works VALUES (?,?,?,?,?,?,?,?,?)', rows)
        c.executemany('INSERT OR IGNORE INTO edges VALUES (?,?)', edge_rows)
        c.executemany('INSERT OR REPLACE INTO seeds VALUES (?,?,?,?)',
                      [(s['file'], s['doi'], s['pubdate'],
                        next((k for k, w in works.items()
                              if wechat_seed.normalize_doi(w.get('doi')) == s['doi']), ''))
                       for s in seeds])
        c.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',
                  ('build', json.dumps({'seed_dir': seed_dir, 'min_df': min_df,
                                        'articles': st['total'], 'seeds': len(works),
                                        'refs': len(counts), 'edges': len(edge_rows)},
                                       ensure_ascii=False)))
    c.close()
    log.info('build 完成：种子 %d / 参考文献 %d / 边 %d'
             % (len(works), len(counts), len(edge_rows)))
    return {'articles': st['total'], 'seeds': len(works), 'refs': len(counts),
            'edges': len(edge_rows), 'backbone': len(refs_meta)}


# ══════════════════════════════════════════════════════════════════════
# 第二步：聚类（纯本地，可反复调参）
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


def cluster(resolutions=(1.5, 2.0, 2.5, 3.0), min_size=5, tries=10, progress=None):
    """从库里读出来聚类，结果写回 clusters 表。返回扫描报告。"""
    say = progress or (lambda *a: None)
    c = _conn()
    seeds, refsets, titles = _load(c)
    if not seeds:
        c.close()
        raise DirectionMapError('库里没有种子，先跑 build()')

    tools = bib.tool_refs(titles)
    say('通用工具类参考文献 %d 条（不参与相似度，保留在地基）' % len(tools))

    keys = sorted(seeds)
    keys, S = bib.coupling_matrix(refsets, exclude=tools, keys=keys)
    say('相似度矩阵 %d×%d，非零边 %d' % (len(keys), len(keys), int((S > 0).sum() / 2)))

    labels, report = bib.best_partition(
        S, keys, lambda k: seeds[k]['topic'] or '?',
        resolutions=resolutions, tries=tries, min_size=min_size)
    for res, q, ncl, cov, p in report:
        say('  res=%.1f | 模块度 %.3f | 簇>=%d %2d | 覆盖 %d/%d | 主题纯度 %.2f'
            % (res, q, min_size, ncl, cov, len(keys), p))
    best_res = max(report, key=lambda r: r[4])[0]
    say('选定 res=%.1f（按主题纯度，不按模块度 —— 见 domain.bibliometrics 说明）' % best_res)

    with c:
        c.execute('DELETE FROM clusters')
        c.executemany('INSERT OR REPLACE INTO clusters VALUES (?,?,?)',
                      [(k, int(l), best_res) for k, l in zip(keys, labels)])
        c.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',
                  ('cluster', json.dumps({'resolution': best_res,
                                          'report': report}, ensure_ascii=False)))
    c.close()
    log.info('cluster 完成：res=%.1f，%d 个节点' % (best_res, len(keys)))
    return report


# ══════════════════════════════════════════════════════════════════════
# 第三步：报告
# ══════════════════════════════════════════════════════════════════════
PERIODS_DEFAULT = None   # None = 自动按库里出现过的半年排序


def report(min_size=5, top_refs=4, out=None):
    """生成人读的方向地图。返回字符串；给 out 就同时写文件。"""
    c = _conn()
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
    L.append('方向地图 · 种子 %s 篇 / 参考文献 %s 篇 / 引用边 %s 条'
             % (b.get('seeds', '?'), b.get('refs', '?'), b.get('edges', '?')))
    L.append('分辨率 %s · %d 个簇（>=%d 篇）'
             % (json.loads(meta.get('cluster', '{}')).get('resolution', '?'),
                len(groups), min_size))
    L.append('⚠ 最后一个时间段可能不满半年，别直接拿它比出「在下降」')
    L.append('')

    for gi, mem in enumerate(groups, 1):
        cnt, series = bib.trend([seeds[k]['wx_date'] for k in mem], all_periods)
        arrow = bib.direction(series)
        topic = collections.Counter(seeds[k]['topic'] or '?' for k in mem).most_common(1)[0][0]
        L.append('--- 簇%-2d | %3d 篇 | %s  %s' % (gi, len(mem), topic[:46], arrow))
        L.append('    趋势 ' + '  '.join('%s:%d' % (p, n) for p, n in zip(all_periods, series)))
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
    for r, n in bib.top_shared(refsets, min_df=1, limit=None)[:30]:
        if r not in ref_info:
            continue
        t, y, v = ref_info[r]
        L.append('  [%2d] %s %-30s %s%s' % (n, y, (v or '?')[:30], (t or '')[:60],
                                            ' [工具]' if r in tools else ''))
    text = '\n'.join(L)
    if out:
        io.open(out, 'w', encoding='utf-8').write(text)
    return text


def stats():
    """库里现在有什么。体检和面板用。"""
    if not os.path.exists(paths.direction_db()):
        return {'exists': False}
    c = _conn()
    g = lambda q: c.execute(q).fetchone()[0]
    s = {'exists': True,
         'seeds': g('SELECT COUNT(*) FROM works WHERE is_seed=1'),
         'refs': g('SELECT COUNT(*) FROM works WHERE is_seed=0'),
         'edges': g('SELECT COUNT(*) FROM edges'),
         'clustered': g('SELECT COUNT(*) FROM clusters'),
         'meta': dict(c.execute('SELECT k,v FROM meta'))}
    c.close()
    return s
