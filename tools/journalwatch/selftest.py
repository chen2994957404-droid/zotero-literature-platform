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
    real = jw.catalog.find
    jw.catalog.find = lambda d: 'doi_x' if d == '10.1/c' else ''
    try:
        rows = jw.annotate([_w('10.1/C'), _w('10.1/D')], {'dois': {}}, today=today)
    finally:
        jw.catalog.find = real
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

    print('\n%d/%d 通过' % (ok, total))
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
