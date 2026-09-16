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
    jw.catalog.by_doi = lambda: {'10.1/c': 'doi_x'}
    try:
        rows = jw.annotate([_w('10.1/C'), _w('10.1/D')], {'dois': {}}, today=today)
    finally:
        jw.catalog.by_doi = real
    if [r['in_library'] for r in rows] == ['doi_x', '']:
        print('  [PASS] 证据库里有的标出 id'); ok += 1
    else:
        print('  [FAIL] 库内标注不对：%s' % rows)

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

    print('\n%d/%d 通过' % (ok, total))
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
