# -*- coding: utf-8 -*-
"""检索结果标「可读」（2026-09-14）：库里有 ≠ 能读，解析过全文的才叫可读。全离线。"""
import io
import os

import pytest

from shared.kernel import catalog, paths
from tools import litsearch


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ('RAW', 'CURATED', 'SERVING'):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(paths, name, str(d))
    monkeypatch.setattr(paths, 'STRUCTURED', str(tmp_path / 'serving' / 'structured'))
    key = 'AAAA0001'
    os.makedirs(paths.parsed_dir(key), exist_ok=True)
    io.open(paths.fulltext(key), 'w', encoding='utf-8').write('# A tough elastomer' + chr(10) + chr(10) + 'body')
    catalog.register(key, doi='10.1000/self', title='A tough elastomer')
    catalog.register('BBBB0002', doi='10.1021/acs.macromol.5b00210', title='Dynamic boronic ester networks')
    return key


def test_检索结果标可读(env, monkeypatch):
    items = [{'title': 'A tough elastomer', 'doi': '10.1000/self'},
             {'title': 'Dynamic boronic ester networks', 'doi': '10.1021/acs.macromol.5b00210'},
             {'title': 'unknown', 'doi': '10.9/none'}]
    litsearch.mark_readable(items)
    assert items[0]['readable'] and items[0]['db_id'] == env, '解析过全文的才叫可读'
    assert not items[1]['readable'] and items[1]['db_id'] == 'BBBB0002', '只有条目没全文：在库但不可读'
    assert not items[2]['readable'] and not items[2]['db_id']


def test_书章节和百科词条要标出来():
    from shared.domain.libmatch import looks_like_book
    assert looks_like_book({'doi': '10.1007/978-3-031-35521-9', 'venue': ''})
    assert looks_like_book({'doi': '10.1039/x', 'venue': 'Encyclopedia of Polymer Science'})
    assert not looks_like_book({'doi': '10.1021/ma100093b', 'venue': 'Macromolecules'})


def test_OpenAlex限流时退到Sciverse_形状一致(monkeypatch, tmp_path):
    """2026-09-14：没 key 跑 3 条就 429。有 Sciverse 就退过去，返回形状必须仍是 (items, total)。"""
    from shared.kernel import errors, paths
    monkeypatch.setattr(paths, 'STATE', str(tmp_path))
    monkeypatch.setattr('shared.adapters.openalex.works_by_filter',
                        lambda *a, **k: (_ for _ in ()).throw(errors.RateLimited('429', service='openalex')))
    monkeypatch.setattr('shared.adapters.sciverse.search_papers',
                        lambda *a, **k: {'total': 42, 'items': [{'title': 'T', 'doi': '10.1/t', 'year': 2024, 'venue': 'J'}]})
    monkeypatch.setattr(litsearch, '_index', lambda force=False: (set(), set()))
    items, total = litsearch.search('boron pi', limit=5)
    assert total == 42 and items[0]['doi'] == '10.1/t' and items[0]['source'] == 'sciverse'
    assert 'bookish' in items[0] and 'readable' in items[0]
    import glob, io, json
    logs = glob.glob(str(tmp_path / 'searches' / 'litsearch_*.jsonl'))
    assert logs, '每次检索要留一行档'
    rec = json.loads(io.open(logs[0], encoding='utf-8').read().splitlines()[-1])
    assert rec['term'] == 'boron pi' and rec['source'].startswith('sciverse')
