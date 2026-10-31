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


def test_Word版SI转成网页看_raw才下载(tmp_path, monkeypatch):
    docx = pytest.importorskip('docx')
    pytest.importorskip('mammoth')
    p = tmp_path / 'si.docx'
    d = docx.Document()
    d.add_paragraph('Synthesis of PBS')
    d.add_table(rows=1, cols=2).rows[0].cells[0].text = 'B(OH)3'
    d.save(str(p))
    monkeypatch.setitem(server._FILES, 'si', lambda pid: str(p))
    r = C.get('/files/ABCD1234/si')
    assert r.status_code == 200 and r.headers['content-type'].startswith('text/html')
    assert 'Synthesis of PBS' in r.text and '<table>' in r.text and '?raw=1' in r.text
    r = C.get('/files/ABCD1234/si', params={'raw': 1})
    assert r.status_code == 200 and r.headers['content-disposition'].startswith('attachment')
