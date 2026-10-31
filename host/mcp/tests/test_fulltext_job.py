# -*- coding: utf-8 -*-
"""取全文作业收尾：这次收进库的文献补作者索引；补不上不连累作业。离线。"""
import io
import json
import os

from host.mcp import fulltext_job
from shared.kernel import paths


def test_只补这次真收进库的(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, 'RAW', str(tmp_path))
    os.makedirs(os.path.dirname(paths.local_pdf('doi_10.1021-a')))
    io.open(paths.local_pdf('doi_10.1021-a'), 'wb').write(b'%PDF')
    prog = tmp_path / 'p.json'
    prog.write_text(json.dumps({'results': [{'id': 'doi_10.1021-a', 'ok': True},
                                            {'id': 'doi_10.1021-b', 'ok': False},     # 没取到正文
                                            {'doi': '10.1/x', 'id': ''}]}), encoding='utf-8')
    assert fulltext_job.landed_ids(str(prog)) == ['doi_10.1021-a']
    assert fulltext_job.landed_ids(str(tmp_path / 'none.json')) == []


def test_补不上只记日志不抛(monkeypatch):
    def boom(pids):
        raise RuntimeError('OpenAlex 限流')
    monkeypatch.setattr('tools.library.oaindex.add', boom)
    assert fulltext_job.fill_index(['doi_10.1021-a']) == 0
    assert fulltext_job.fill_index([]) == 0
