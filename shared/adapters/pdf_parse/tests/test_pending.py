# -*- coding: utf-8 -*-
"""MineRU 超时后接着查原任务、不重新上传（2026-10-02：忙时一篇排了 17 分钟还是 pending，每次重试都从队尾重排）。"""
import io
import json
import os
import zipfile

import pytest

from shared.adapters import pdf_parse as P


@pytest.fixture
def env(tmp_path, monkeypatch):
    pdf = tmp_path / 'main.pdf'
    pdf.write_bytes(b'%PDF-1.4 fake')
    out = tmp_path / 'parsed'
    out.mkdir()
    calls = {'upload': 0, 'state': 'pending'}
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, 'w') as z:
        z.writestr('full.md', '# T\n')
        z.writestr('layout.json', '{}')

    def fake_api(path, method='GET', body=None):
        if path.startswith('/file-urls/batch'):
            calls['upload'] += 1
            return {'data': {'batch_id': 'B%d' % calls['upload'], 'file_urls': ['https://up.example/x?y=1']}}
        return {'data': {'extract_result': [{'state': calls['state'], 'full_zip_url': 'https://zip.example/z'}]}}

    class FakeConn:
        def __init__(self, *a, **k): pass
        def request(self, *a, **k): pass
        def getresponse(self):
            class R:
                status = 200
                def read(self): return b''
            return R()
        def close(self): pass

    monkeypatch.setattr(P, '_api', fake_api)
    monkeypatch.setattr(P._hc, 'HTTPSConnection', FakeConn)
    monkeypatch.setattr(P.time, 'sleep', lambda s: None)
    monkeypatch.setattr(P, 'POLL_MAX_S', 16)
    monkeypatch.setattr(P.urllib.request, 'urlopen', lambda url, timeout=0: io.BytesIO(zbuf.getvalue()))
    monkeypatch.setattr(P, 'link_origin', lambda *a: None)
    return str(pdf), str(out), calls


def test_超时后再解析_接着查原任务_不重新上传(env):
    pdf, out, calls = env
    with pytest.raises(P.PDFParseError, match='接着等'):
        P._parse_once(pdf, out, 'vlm', True)
    assert calls['upload'] == 1 and os.path.exists(os.path.join(out, P._PENDING))
    calls['state'] = 'done'
    P._parse_once(pdf, out, 'vlm', True)
    assert calls['upload'] == 1, '有没等完的任务就接着查，不许重新上传（那等于排到队尾）'
    assert os.path.exists(os.path.join(out, 'full.md'))
    assert not os.path.exists(os.path.join(out, P._PENDING)), '做完要清掉记录'


def test_明确失败了_下次重新上传(env):
    pdf, out, calls = env
    calls['state'] = 'failed'
    with pytest.raises(P.PDFParseError, match='解析失败'):
        P._parse_once(pdf, out, 'vlm', True)
    assert not os.path.exists(os.path.join(out, P._PENDING))


def test_文件换了_不接旧任务(env):
    pdf, out, calls = env
    with pytest.raises(P.PDFParseError):
        P._parse_once(pdf, out, 'vlm', True)
    io.open(pdf, 'ab').write(b' changed')
    calls['state'] = 'done'
    P._parse_once(pdf, out, 'vlm', True)
    assert calls['upload'] == 2
