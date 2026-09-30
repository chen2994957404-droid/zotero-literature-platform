# -*- coding: utf-8 -*-
"""查询库的自刷新：**库比源 JSON 旧就自己重建**。

R7 窗之前是「谁写完 `structured/<key>.json` 谁负责刷索引」，于是
`tools/extract` 里写着 `from tools import paperdb` —— 违反 REBUILD.md
第三节硬规则 2（工具不许 import 工具）。

真正的毛病不在那行 import，而在**责任放错了地方**：索引的新鲜度是索引自己的事。
让写入方负责，就得每个写 JSON 的人都记得刷一次；漏一个（手改过 JSON、
从别处拷进来一份、B 机同步过来一批）用户就查到旧数据，**而且不报错**。

所以这条测试要钉死的是：**新写一份 JSON 之后，下一次查询必须看得见它。**
"""
import io
import json
import os
import time

import pytest

from tools import paperdb


@pytest.fixture
def db(isolate):
    """源与库都在临时目录里（隔离清单见 conftest.py）。"""
    return isolate


def _write(st, key, title):
    io.open(st / f'{key}.json', 'w', encoding='utf-8').write(
        json.dumps({'key': key, 'title': title, 'schema_ver': 1},
                   ensure_ascii=False))


def test_新写一份JSON之后查询就能看见它(db):
    _write(db, 'AAAA1111', '第一篇')
    assert [r['key'] for r in paperdb.query('SELECT key FROM papers')] == ['AAAA1111']

    # 库刚建好，时间戳可能与新 JSON 同秒 —— 把新文件的时间往后推，
    # 模拟「先建库、后来又抽了一篇」这个真实顺序（同秒不算旧，见 _ensure_fresh）。
    _write(db, 'BBBB2222', '第二篇')
    os.utime(db / 'BBBB2222.json', (time.time() + 2, time.time() + 2))

    keys = sorted(r['key'] for r in paperdb.query('SELECT key FROM papers'))
    assert keys == ['AAAA1111', 'BBBB2222'], (
        '写了新 JSON 却查不到 —— 索引的新鲜度没人负责了')


def test_删掉一份JSON之后它也从查询里消失(db):
    _write(db, 'AAAA1111', '第一篇')
    _write(db, 'BBBB2222', '第二篇')
    assert len(paperdb.query('SELECT key FROM papers')) == 2

    os.remove(db / 'BBBB2222.json')
    os.utime(str(db), None)          # 目录变了，但判据看的是文件时间
    _write(db, 'AAAA1111', '第一篇（改过）')
    os.utime(db / 'AAAA1111.json', (time.time() + 2, time.time() + 2))

    assert [r['key'] for r in paperdb.query('SELECT key FROM papers')] == ['AAAA1111'], (
        'rebuild 是整库重建，删掉的记录必须跟着消失（这正是不做增量的理由）')


def test_没有源JSON时不要把已有的库清空(db):
    """B 机把 papers.db 同步过来、但 structured/ 还没同步完时，别把库洗了。"""
    _write(db, 'AAAA1111', '第一篇')
    assert len(paperdb.query('SELECT key FROM papers')) == 1
    os.remove(db / 'AAAA1111.json')
    assert len(paperdb.query('SELECT key FROM papers')) == 1, (
        '源目录空了应保持现状，而不是把库清空 —— 空结果看起来像「没这篇」，'
        '比报错更难发现')


def test_表结构改过_旧库时间再新也要重建_不许变空(db):
    """2026-09-30：measurements 加了推导列。旧库时间戳是新的，只看时间就不重建；
    而 connect() 会把列对不上的旧表整张丢掉 —— 数值库变空、不报错。"""
    import sqlite3
    _write(db, 'AAAA1111', '第一篇')
    assert paperdb.query('SELECT key FROM papers')           # 先建好
    p = paperdb.db_path()
    paperdb._conn_cache.clear()
    c = sqlite3.connect(p)
    c.executescript('DROP TABLE papers; CREATE TABLE papers (key TEXT, title TEXT);'
                    "INSERT INTO papers VALUES ('OLD', 'old layout');")
    c.commit(); c.close()
    os.utime(p, (time.time() + 60, time.time() + 60))         # 库比源新得多
    assert not paperdb.schema_current(p)
    assert [r['key'] for r in paperdb.query('SELECT key FROM papers')] == ['AAAA1111']
