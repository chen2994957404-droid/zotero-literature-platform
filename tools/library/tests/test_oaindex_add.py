# -*- coding: utf-8 -*-
"""oaindex.add：只给新收进库的几篇补作者 + 摘要（假 OpenAlex，离线）。"""
import pytest

from shared.kernel import catalog, paths
from tools.library import oaindex


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ('RAW', 'CURATED', 'SERVING'):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(paths, name, str(d))
    catalog.register('doi_10.1021-old', doi='10.1021/old', title='Old')
    catalog.register('doi_10.1021-new', doi='10.1021/new', title='New')
    asked = []

    def fake(dois, select=None, on_progress=None, allow_partial=False):
        asked.append(sorted(dois))
        return {'W' + d[-3:]: {'id': 'https://openalex.org/W' + d[-3:], 'doi': 'https://doi.org/' + d,
                               'publication_year': 2025, 'authorships': [], 'primary_location': {}}
                for d in dois}
    monkeypatch.setattr('shared.adapters.openalex.works_by_dois', fake)
    return asked


def test_只查索引里没有的那几篇(env):
    assert oaindex.add(['doi_10.1021-old']) == 1 and env == [['10.1021/old']]
    assert oaindex.add(['doi_10.1021-old', 'doi_10.1021-new']) == 1 and env[-1] == ['10.1021/new']
    assert set((oaindex.load() or {}).get('papers', {})) == {'doi_10.1021-old', 'doi_10.1021-new'}
    assert oaindex.add(['doi_10.1021-old']) == 0 and len(env) == 2      # 都有了：一次都不查


def test_没有DOI的不查(env):
    catalog.register('AAAA0001', title='知网来的，没有 DOI')
    assert oaindex.add(['AAAA0001']) == 0 and env == []
