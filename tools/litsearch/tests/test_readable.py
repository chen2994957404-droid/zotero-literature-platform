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
