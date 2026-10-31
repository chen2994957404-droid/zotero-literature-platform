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


def test_Word版SI的地址可以带docx结尾(tmp_path, monkeypatch):
    # Word 经 ms-word: 链接来取，地址不以 .docx 结尾它不认
    p = tmp_path / 'si.docx'
    p.write_bytes(b'PK\x03\x04 fake docx')
    monkeypatch.setitem(server._FILES, 'si', lambda pid: str(p))
    assert C.get('/files/ABCD1234/si.docx').status_code == 200
    p.write_bytes(b'%PDF-1.7 fake')                                    # 名字是 docx、里面是 PDF（#181）
    assert C.get('/files/ABCD1234/si').headers['content-type'] == 'application/pdf'
