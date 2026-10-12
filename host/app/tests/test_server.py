# -*- coding: utf-8 -*-
"""文献库应用后台（host.app.server）—— 全离线：不需要证据库里有数据。

守三件事：接口都在、只接受本机 Host、文件接口不让人拿任意路径。"""
import pytest

pytest.importorskip('fastapi')
pytest.importorskip('httpx')
from fastapi.testclient import TestClient

from host.app import server

C = TestClient(server.app)


def test_接口都在():
    assert C.get('/api/meta').status_code == 200
    assert C.get('/api/teams').status_code == 200
    r = C.get('/api/search', params={'q': 'zzzz-not-a-word-zzzz'})
    assert r.status_code == 200 and r.json()['total'] == 0


def test_只接受本机Host():
    evil = TestClient(server.app, base_url='http://evil.example')
    assert evil.get('/api/meta').status_code == 403


def test_文件接口不让拿任意路径():
    assert C.get('/files/ABCD1234/passwd').status_code == 404          # 不认识的文件种类
    assert C.get('/files/..%2F..%2Fsecret/pdf').status_code == 404     # 不合法的 id
    assert C.get('/api/paper/not-an-id').status_code == 404


def test_精读_花钱的请求只认本应用页面():
    assert C.post('/api/deepread/ABCD1234').status_code == 403                              # 没带自定义头
    r = C.post('/api/deepread/ABCD1234', headers={'X-Literature-App': '1', 'Origin': 'http://evil.example'})
    assert r.status_code == 403                                                              # 别的来源
    r = C.post('/api/deepread/ABCD1234', headers={'X-Literature-App': '1'})
    assert r.status_code == 409                                                              # 本地没文件：不排队


def test_作业队列_同一篇不重复排(tmp_path, monkeypatch):
    from shared.kernel import paths
    from host.app import jobs
    monkeypatch.setattr(paths, 'STATE', str(tmp_path))
    a, new1 = jobs.enqueue('doi_10.1-x')
    b, new2 = jobs.enqueue('doi_10.1-x')
    assert new1 and not new2 and a['id'] == b['id']
    j = jobs.next_queued()
    assert j is not None
    jobs.mark(j['id'], 'running')
    assert jobs.next_queued() is None
    jobs.mark(j['id'], 'done', '正文精读完成')
    last = jobs.of('doi_10.1-x')
    assert last is not None and last['state'] == 'done'
    _, new3 = jobs.enqueue('doi_10.1-x')                                                    # 做完了可以再排
    assert new3
