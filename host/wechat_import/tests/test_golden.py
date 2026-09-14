# -*- coding: utf-8 -*-
"""金标配对：推文当范文存起来、原件进证据库、残件与无 DOI 的不配（2026-09-14）。

全离线：`getpdf.land` 换成假替身。测的是配对与索引，不是取件。
"""
import io
import json
import os

import pytest

from shared.kernel import paths
from host.wechat_import import golden

DOI = '10.1021/acs.macromol.6c00991'
FULL = ('# 【Macromolecules】阳离子-π 相邻基元让溶液在剪切下成胶\n\n'
        '原创 高分子学人 _2026年9月1日_\n\n'
        + '\n\n'.join('这是第 %d 段正文，讲机理与数据，长度凑够范文的门槛。' % i * 6
                      for i in range(1, 20))
        + '\n\n![](https://mmbiz.qpic.cn/x/1.jpg)\n\n再来一段讨论。' * 3
        + '\n\nhttps://doi.org/  ' + DOI + '\n\n二维码\n')


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ('RAW', 'CURATED', 'STATE'):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(paths, name, str(d))
    calls = []

    def fake_land(doi, with_si=True, allow_fetch=True, **kw):
        calls.append((doi, allow_fetch))
        pid = paths.paper_id_from_doi(doi)
        paths.paper_raw_dir(pid, create=True)
        return {'doi': doi, 'id': pid, 'ok': True, 'action': 'landed',
                'pdf': 'x.pdf', 'si': ''}

    from tools import getpdf
    monkeypatch.setattr(getpdf, 'land', fake_land)
    return calls


def _md(tmp_path, text, name='a.md'):
    p = tmp_path / name
    io.open(str(p), 'w', encoding='utf-8').write(text)
    return str(p)


def test_配上一篇_范文与索引都在(env, tmp_path):
    r = golden.pair(_md(tmp_path, FULL))
    assert r['action'] == 'paired', r
    pid = r['id']
    ref = io.open(paths.reference(pid), encoding='utf-8').read()
    assert 'DOI: ' + DOI in ref and '![](https://mmbiz.qpic.cn/x/1.jpg)' in ref
    assert '二维码' not in ref                     # 文末噪音不进范文
    idx = golden.load_index()
    assert idx[pid]['doi'] == DOI and idx[pid]['chars'] >= golden.MIN_REF_CHARS
    meta = json.load(io.open(paths.meta(pid), encoding='utf-8'))
    assert meta['reference'] == '高分子学人'
    assert not os.path.exists(paths.summary(pid))   # 绝不冒充精读


def test_再跑一遍是exists_不覆盖范文(env, tmp_path):
    p = _md(tmp_path, FULL)
    golden.pair(p)
    r = golden.pair(p)
    assert r['action'] == 'exists' and len(golden.load_index()) == 1


def test_残件与无DOI都跳过_不取件(env, tmp_path):
    short = FULL.replace('这是第', '第')[:600] + '\n\nhttps://doi.org/ ' + DOI + '\n'
    r1 = golden.pair(_md(tmp_path, short, 'b.md'))
    r2 = golden.pair(_md(tmp_path, '# 招聘启事\n\n正文' * 300, 'c.md'))
    assert r1['action'] == 'skipped' and '残件' in r1['note']
    assert r2['action'] == 'skipped' and 'DOI' in r2['note']
    assert env == []


def test_只用手上有的_不向出版商取(env, tmp_path):
    golden.pair(_md(tmp_path, FULL), allow_fetch=False)
    assert env == [(DOI, False)]


def test_两路并发_按出版商错开_结果齐全(env, tmp_path):
    files = [_md(tmp_path, FULL.replace(DOI, '10.1021/a%d' % i), 'acs%d.md' % i) for i in range(3)]
    files += [_md(tmp_path, FULL.replace(DOI, '10.1002/w%d' % i), 'wiley%d.md' % i) for i in range(3)]
    order = golden._interleave(files)
    assert [os.path.basename(p)[:3] for p in order] == ['acs', 'wil'] * 3
    res = golden.build(files, allow_fetch=False, log=lambda *a: None, workers=2)
    assert sum(1 for r in res if r['action'] == 'paired') == 6 and len(golden.load_index()) == 6
