# -*- coding: utf-8 -*-
"""0 级文献雷达的存储（SQLite，`paths.radar_db()`）。2026-09-15。

一篇 = 一行 works（题目 / 摘要 / 作者 / 刊 / 日期 / 被引）+ 若干行 refs（它引了哪些 DOI）。
`in_library` 是登记时对证据库的快照，`refresh_library_flags()` 可以重算。

只做存和取，不联网、不判相关度。
"""
import datetime as _dt
import json
import os
import sqlite3

from shared.kernel import paths

SCHEMA = '''
CREATE TABLE IF NOT EXISTS works (
    doi TEXT PRIMARY KEY, title TEXT, venue TEXT, issn TEXT, publisher TEXT,
    year INTEGER, published TEXT, created TEXT, abstract TEXT, first_author TEXT,
    authors TEXT, citations INTEGER, in_library TEXT, first_seen TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS refs (doi TEXT, ref_doi TEXT, PRIMARY KEY (doi, ref_doi));
CREATE INDEX IF NOT EXISTS ix_works_venue ON works(venue);
CREATE INDEX IF NOT EXISTS ix_works_published ON works(published);
CREATE INDEX IF NOT EXISTS ix_refs_ref ON refs(ref_doi);
'''


def connect(path=None):
    path = path or paths.radar_db()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.execute('PRAGMA journal_mode=WAL')
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute('PRAGMA table_info(works)')}
    for col, typ in (('tier', 'TEXT'), ('lib_cites', 'INTEGER'), ('topics', 'TEXT'), ('subfields', 'TEXT')):
        if col not in have:
            con.execute('ALTER TABLE works ADD COLUMN %s %s' % (col, typ))       # 2026-09-16 加：档位与引库内几篇
    return con


def upsert(con, items, source='crossref', today=None):
    """写入一批 normalize 后的文献。已有的更新元数据（摘要、被引会变），**不动 first_seen**。返回新增几篇。"""
    today = (today or _dt.date.today()).isoformat()
    new = 0
    for w in items:
        doi = (w.get('doi') or '').lower()
        if not doi:
            continue
        row = con.execute('SELECT first_seen FROM works WHERE doi=?', (doi,)).fetchone()
        if row is None:
            new += 1
        con.execute('''INSERT INTO works (doi,title,venue,issn,publisher,year,published,created,abstract,
                       first_author,authors,citations,in_library,first_seen,source,tier,lib_cites)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(doi) DO UPDATE SET title=excluded.title, venue=excluded.venue,
                       publisher=excluded.publisher, year=excluded.year, published=excluded.published,
                       abstract=CASE WHEN length(excluded.abstract)>length(coalesce(works.abstract,'')) THEN excluded.abstract ELSE works.abstract END,
                       authors=excluded.authors, citations=excluded.citations,
                       in_library=CASE WHEN excluded.in_library<>'' THEN excluded.in_library ELSE works.in_library END,
                       tier=coalesce(excluded.tier, works.tier), lib_cites=coalesce(excluded.lib_cites, works.lib_cites)''',
                    (doi, w.get('title', ''), w.get('venue', ''), w.get('issn', ''), w.get('publisher', ''),
                     w.get('year'), w.get('published', ''), w.get('created', ''), w.get('abstract', ''),
                     w.get('first_author', ''), json.dumps(w.get('authors') or [], ensure_ascii=False),
                     int(w.get('citations') or 0), w.get('in_library', '') or '', today, source,
                     w.get('tier'), w.get('lib_cites')))
        refs = w.get('refs') or []
        if refs:
            con.executemany('INSERT OR IGNORE INTO refs (doi, ref_doi) VALUES (?,?)', [(doi, r) for r in refs])
    con.commit()
    return new


def stats(con):
    n = con.execute('SELECT count(*) FROM works').fetchone()[0]
    ab = con.execute("SELECT count(*) FROM works WHERE length(abstract)>200").fetchone()[0]
    lib = con.execute("SELECT count(*) FROM works WHERE in_library<>''").fetchone()[0]
    nref = con.execute('SELECT count(*) FROM refs').fetchone()[0]
    span = con.execute('SELECT min(published), max(published) FROM works').fetchone()
    by_venue = con.execute('SELECT venue, count(*) FROM works GROUP BY venue ORDER BY 2 DESC').fetchall()
    return {'works': n, 'with_abstract': ab, 'in_library': lib, 'refs': nref, 'span': span, 'by_venue': by_venue}


def cited_in_library(con, library_dois):
    """雷达里的每篇引了证据库里几篇 → [(doi, n)]，按 n 降序。相关度筛选的原料之一。"""
    if not library_dois:
        return []
    con.execute('CREATE TEMP TABLE IF NOT EXISTS lib (doi TEXT PRIMARY KEY)')
    con.execute('DELETE FROM lib')
    con.executemany('INSERT OR IGNORE INTO lib VALUES (?)', [(d.lower(),) for d in library_dois])
    return con.execute('''SELECT r.doi, count(*) n FROM refs r JOIN lib ON lib.doi=r.ref_doi
                          GROUP BY r.doi ORDER BY n DESC''').fetchall()


def refresh_library_flags(con, find):
    """重算 in_library（证据库后来收了的要标上）。find: doi → id 或 ''。返回改了几行。"""
    n = 0
    for (doi,) in con.execute("SELECT doi FROM works WHERE in_library=''").fetchall():
        pid = find(doi)
        if pid:
            con.execute('UPDATE works SET in_library=? WHERE doi=?', (pid, doi)); n += 1
    con.commit()
    return n


def refresh_lib_cites(con, library_dois, tiers=None):
    """重算每篇「引了库内几篇」（证据库长了、或回填时还没算）；顺便按刊名补档位。返回引了库内的篇数。"""
    rows = cited_in_library(con, library_dois)
    con.execute('UPDATE works SET lib_cites=0 WHERE lib_cites IS NULL')
    con.executemany('UPDATE works SET lib_cites=? WHERE doi=?', [(n, d) for d, n in rows])
    if tiers:
        con.executemany('UPDATE works SET tier=? WHERE venue=? AND (tier IS NULL OR tier<>?)',
                        [(t, v, t) for v, t in tiers.items()])
    con.commit()
    return len(rows)
