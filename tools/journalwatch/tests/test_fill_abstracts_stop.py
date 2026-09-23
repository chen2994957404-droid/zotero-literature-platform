# -*- coding: utf-8 -*-
"""补摘要：OpenAlex 一批被拒就整轮停下，不再逐批空转（2026-09-24 主力机 daily 卡住一个多小时）。"""
import sqlite3

from shared.kernel import errors
import tools.journalwatch as JW


def test_额度用完一批被拒就停_不逐批空转(monkeypatch):
    con = sqlite3.connect(':memory:')
    con.execute('CREATE TABLE works (doi TEXT, abstract TEXT, publisher TEXT, published TEXT)')
    con.executemany('INSERT INTO works VALUES (?,?,?,?)', [('10.1/%d' % i, '', 'Wiley', '2026') for i in range(500)])

    class _Con:
        def __getattr__(self, n):
            return getattr(con, n)

        def close(self):
            pass
    monkeypatch.setattr(JW.store, 'connect', lambda: _Con())
    saved = {}
    monkeypatch.setattr(JW, 'load_seen', lambda: {})
    monkeypatch.setattr(JW, 'save_seen', lambda s: saved.update(s))
    calls = []

    def refuse(chunk, allow_partial=False):
        calls.append(allow_partial)
        raise errors.RateLimited('额度用尽', service='openalex')
    monkeypatch.setattr(JW.openalex, 'works_by_dois', refuse)
    filled, asked = JW.fill_abstracts(max_calls=10, log=lambda *a: None)
    assert filled == 0 and len(calls) == 1, '第一批被拒就该停，不该把 10 批都问一遍'
    assert calls == [False]
