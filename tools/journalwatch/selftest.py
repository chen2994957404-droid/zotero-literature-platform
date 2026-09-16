# -*- coding: utf-8 -*-
"""journalwatch 自测：不联网、不碰用户数据。验「去重 / 标库里有 / 首见只记一次 / 清单开关」。"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import datetime
import io
import json
import os
import tempfile

from tools import journalwatch as jw


def _w(doi, title='T', venue='J', created='2026-09-10'):
    return {'doi': doi, 'title': title, 'venue': venue, 'created': created, 'published': created,
            'type': 'journal-article', 'abstract': '', 'year': 2026, 'citations': 0}


def main():
    ok = total = 0
    today = datetime.date(2026, 9, 15)

    total += 1
    seen = {'dois': {}, 'checked': {}}
    rows = jw.annotate([_w('10.1/A'), _w('10.1/a'), _w('10.1/B')], seen, today=today)
    if [r['doi'] for r in rows] == ['10.1/A', '10.1/B'] and all(r['is_new'] for r in rows):
        print('  [PASS] 同一 DOI 大小写不同只算一篇；首次全是「新」'); ok += 1
    else:
        print('  [FAIL] 去重/首见不对：%s' % rows)

    total += 1
    rows = jw.annotate([_w('10.1/A'), _w('10.1/C')], seen, today=today)
    if [(r['doi'], r['is_new']) for r in rows] == [('10.1/A', False), ('10.1/C', True)] \
            and seen['dois']['10.1/a'] == '2026-09-15':
        print('  [PASS] 第二次见到的不再是「新」；首见日只记一次'); ok += 1
    else:
        print('  [FAIL] 二次标注不对：%s %s' % (rows, seen))

    total += 1
    real = jw.catalog.by_doi
    jw.catalog.by_doi = lambda: {'10.1/c': 'doi_x', '10.1/l1': 'p1', '10.1/l2': 'p2'}
    try:
        a = dict(_w('10.1/C'), tier='A', refs=['10.1/l1', '10.1/l2', '10.1/zz'])   # A 档引 2 篇 → 过线
        b = dict(_w('10.1/D'), tier='C', refs=['10.1/l1', '10.1/l2'])              # C 档引 2 篇 → 不过（要 3）
        c = dict(_w('10.1/E'), tier='B', refs=['10.1/l1'])                         # B 档引 1 篇 → 过
        rows = jw.annotate([a, b, c], {'dois': {}}, today=today)
    finally:
        jw.catalog.by_doi = real
    got = {r['doi']: (r['in_library'], r['lib_cites'], r['passes']) for r in rows}
    if got == {'10.1/C': ('doi_x', 2, True), '10.1/D': ('', 2, False), '10.1/E': ('', 1, True)}:
        print('  [PASS] 证据库里有的标出 id；引了库内几篇 + 按档位过线（A≥2 / B≥1 / C≥3）'); ok += 1
    else:
        print('  [FAIL] 库内标注 / 门槛不对：%s' % got)

    total += 1
    p = os.path.join(tempfile.mkdtemp(), 'jw.json')
    js = jw.load_journals(p)
    js2 = None
    if os.path.exists(p) and len(js) == len(jw.DEFAULT_JOURNALS):
        d = json.loads(io.open(p, encoding='utf-8').read())
        d['journals'][0]['off'] = True
        io.open(p, 'w', encoding='utf-8').write(json.dumps(d))
        js2 = jw.load_journals(p)
    if js2 is not None and len(js2) == len(js) - 1:
        print('  [PASS] 没清单就用种子建一份；"off": true 的刊不盯'); ok += 1
    else:
        print('  [FAIL] 清单加载不对')

    total += 1
    if jw._since(7, today) == '2026-09-08' and jw._since(999, today) == (today - datetime.timedelta(days=jw.MAX_DAYS)).isoformat():
        print('  [PASS] 窗口按天数算，最长 %d 天' % jw.MAX_DAYS); ok += 1
    else:
        print('  [FAIL] 窗口计算不对')

    total += 1
    calls = []
    real_f = jw.crossref.journal_works_since
    def fake(issn, since):
        calls.append(issn)
        if issn == 'bad':
            raise jw.crossref.CrossrefError('x')
        return [_w('10.1/%s' % issn)]
    jw.crossref.journal_works_since = fake
    try:
        items, failed = jw.fetch([{'name': 'Good', 'issn': 'g1'}, {'name': 'Bad', 'issn': 'bad'}],
                                 days=7, log=lambda *a: None, today=today)
    finally:
        jw.crossref.journal_works_since = real_f
    if failed == ['Bad'] and [w['venue'] for w in items] == ['Good']:
        print('  [PASS] 一本刊查挂了只记一笔，其余照常；刊名用清单里的'); ok += 1
    else:
        print('  [FAIL] 容错不对：%s %s' % (items, failed))

    total += 1
    # 回填：按年切块、翻页、断点续跑（假的 crossref + 临时库 + 临时进度文件）
    import shutil
    tmpd = tempfile.mkdtemp()
    real_db, real_seen, real_rt = jw.paths.radar_db, jw.paths.journal_watch_seen, jw.paths.runtime
    jw.paths.radar_db = lambda: os.path.join(tmpd, 'r.db')
    jw.paths.journal_watch_seen = lambda: os.path.join(tmpd, 'seen.json')
    jw.paths.runtime = lambda name, **kw: os.path.join(tmpd, name)     # 心跳信号也别落到真实目录
    pages = {'*': ([_w('10.1/p1'), _w('10.1/p2')], 'c2'), 'c2': ([_w('10.1/p3')], '')}
    calls = []

    def fake_jw(issn, flt, rows=1000, cursor='*'):
        calls.append((flt, cursor))
        it, nxt = pages[cursor]
        return it, nxt, 3
    real_jw = jw.crossref.journal_works
    jw.crossref.journal_works = fake_jw
    try:
        r1 = jw.backfill(years=2, journals=[{'name': 'J', 'issn': 'x'}], log=lambda *a: None,
                         until=datetime.date(2026, 9, 15))
        r2 = jw.backfill(years=2, journals=[{'name': 'J', 'issn': 'x'}], log=lambda *a: None,
                         until=datetime.date(2026, 9, 15))
        con = jw.store.connect()
        n = jw.store.stats(con)['works']
        con.close()
    finally:
        jw.crossref.journal_works = real_jw
        jw.paths.radar_db, jw.paths.journal_watch_seen, jw.paths.runtime = real_db, real_seen, real_rt
        shutil.rmtree(tmpd, ignore_errors=True)
    if (r1['chunks'] == 2 and r2['chunks'] == 0 and n == 3 and len(calls) == 4
            and calls[0][0].startswith('from-pub-date:2024-09-15,until-pub-date:2025-09-15')):
        print('  [PASS] 回填按年切块、翻页到底、入库去重、第二次跑跳过做过的块'); ok += 1
    else:
        print('  [FAIL] 回填不对：%s %s n=%d calls=%s' % (r1, r2, n, calls))

    total += 1
    tmpd = tempfile.mkdtemp()
    real_seen = jw.paths.journal_watch_seen
    jw.paths.journal_watch_seen = lambda: os.path.join(tmpd, 'seen.json')
    try:
        items = [dict(_w('10.1/q1'), passes=True, tier='B', lib_cites=1, in_library=''),
                 dict(_w('10.1/q2'), passes=True, tier='A', lib_cites=4, in_library=''),
                 dict(_w('10.1/q3'), passes=False, tier='A', lib_cites=1, in_library=''),
                 dict(_w('10.1/q4'), passes=True, tier='A', lib_cites=9, in_library='doi_x')]
        n_in = jw.enqueue_passing(items)
        order = [d for d, _ in jw.next_to_harvest(5)]
        jw.mark_harvest('10.1/q2', True)
        for _ in range(jw.MAX_ATTEMPTS):
            jw.mark_harvest('10.1/q1', False, 'no pdf')
        left = [d for d, _ in jw.next_to_harvest(5)]
        again = jw.enqueue_passing(items)
    finally:
        jw.paths.journal_watch_seen = real_seen
    if n_in == 2 and order == ['10.1/q2', '10.1/q1'] and left == [] and again == 0:
        print('  [PASS] 过线入队（不过线 / 库里有的不进）、引库内多的先取、取成出队、试满四次不再取、不重复入队'); ok += 1
    else:
        print('  [FAIL] 队列不对：%s %s %s %s' % (n_in, order, left, again))

    print('\n%d/%d 通过' % (ok, total))
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
