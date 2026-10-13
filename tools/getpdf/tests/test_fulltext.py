# -*- coding: utf-8 -*-
"""四层回退：**每一层都不许多花上一层的代价**（2026-09-08）。

全离线：不连出版商、不调 MineRU、不碰真实数据。
取和解析都用假的替身 —— 这一组测的是**编排**，不是那两个外部服务。
"""
import io
import os

import pytest

from shared.kernel import paths
from tools.getpdf import fulltext as F

DOI = '10.1021/acs.macromol.1c00123'


@pytest.fixture
def env(tmp_path, monkeypatch):
    """raw/curated/state 全指到临时目录；取与解析都换成计数器替身。"""
    for name in ('RAW', 'CURATED', 'STATE'):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(paths, name, str(d))
    calls = {'fetch': 0, 'parse': 0}

    def fake_fetch(doi):
        calls['fetch'] += 1
        p = tmp_path / 'downloaded.pdf'
        io.open(p, 'wb').write(b'%PDF-1.4 fake')
        return {'doi': doi, 'ok': True, 'reason': 'ok', 'path': str(p),
                'title': 'T', 'landing': 'L', 'bytes': 13}

    def fake_parse(pdf_path, out_dir, reuse=True):
        calls['parse'] += 1
        os.makedirs(out_dir, exist_ok=True)
        io.open(os.path.join(out_dir, 'full.md'), 'w', encoding='utf-8').write(
            '# T\n\n## 3. Results\n\nTensile strength of 12 MPa.\n')

    from tools import getpdf
    monkeypatch.setattr(getpdf, 'fetch_one', fake_fetch)
    monkeypatch.setattr(getpdf, 'fetch_si_one', lambda d, where=None: {
        'doi': d, 'ok': False, 'reason': 'no_si', 'path': '', 'bytes': 0})
    # land() 走「一次落地取正文 + SI」：离线测试里它就是上面两个假替身拼起来
    monkeypatch.setattr(getpdf, 'fetch_pair',
                        lambda d, where=None: (getpdf.fetch_one(d), getpdf.fetch_si_one(d)))
    # 登记元数据会问 Crossref —— 离线测试里让它「查不到」，落地不受影响
    monkeypatch.setattr('shared.adapters.crossref.work',
                        lambda d: (_ for _ in ()).throw(RuntimeError('offline')))
    monkeypatch.setattr('shared.adapters.pdf_parse.parse_pdf', fake_parse)
    return calls


def test_第四层_没有的就去取并解析(env):
    r = F.one(DOI)
    assert r['ok'] and r['source'] == F.SRC_FETCH
    assert env == {'fetch': 1, 'parse': 1}
    assert r['id'] == paths.paper_id_from_doi(DOI), '库里没有就用 DOI 生成的 id'


def test_第一层_解析过了就秒回_一分钱不花(env):
    F.one(DOI)
    env.update(fetch=0, parse=0)
    r = F.one(DOI)
    assert r['ok'] and r['source'] == F.SRC_CACHE
    assert env == {'fetch': 0, 'parse': 0}, '缓存命中还去取/解析 = 白花钱'


def test_第二层_本地有PDF就只解析不下载(env):
    pid = paths.paper_id_from_doi(DOI)
    os.makedirs(os.path.dirname(paths.local_pdf(pid)), exist_ok=True)
    io.open(paths.local_pdf(pid), 'wb').write(b'%PDF-1.4 already here')
    r = F.one(DOI)
    assert r['source'] == F.SRC_LOCAL
    assert env['fetch'] == 0, '本地已有还去敲出版商 = 白担一次风控风险'
    assert env['parse'] == 1


def test_撞上人机验证的整批跑完后补试一次(env, monkeypatch):
    from shared.adapters import pdf_fetch
    monkeypatch.setattr(F, 'RETRY_COOLDOWN', 0)
    tries = {}
    real_one = F.one
    def flaky(doi, allow_fetch=True, upgrader=None):
        tries[doi] = tries.get(doi, 0) + 1
        if doi.endswith('/b') and tries[doi] == 1:
            return {'doi': doi, 'id': '', 'ok': False, 'source': F.SRC_FETCH, 'secs': 0, 'chars': 0,
                    'why': '正文没取到 —— ' + pdf_fetch.REASONS['captcha']}
        if doi.endswith('/c'):
            return {'doi': doi, 'id': '', 'ok': False, 'source': F.SRC_FETCH, 'secs': 0, 'chars': 0,
                    'why': '正文没取到 —— ' + pdf_fetch.REASONS['no_access']}
        return real_one(doi, allow_fetch, upgrader)
    monkeypatch.setattr(F, 'one', flaky)
    rs = F.many(['10.1021/a', '10.1021/b', '10.1021/c'], gap=0, limit=3)
    assert [r['ok'] for r in rs] == [True, True, False]
    assert tries == {'10.1021/a': 1, '10.1021/b': 2, '10.1021/c': 1}, '只有被验证挡住的才补试，没权限的不白敲'


# ── 2026-10-04：解析分两层、状态码、撞验证不卡别家（Claude Science 的需求文档 P0）────────

def _real_pdf(path, reps=30):
    """用 PyMuPDF 现做一份有文字层的 PDF（快速层要真能抽出字）。"""
    import fitz
    doc = fitz.open()
    body = ' '.join('tensile strength of the borosiloxane network reached 12 MPa' for _ in range(reps))
    for title in ('1. Introduction', '2. Results and Discussion'):
        page = doc.new_page()
        page.insert_text((72, 80), title, fontsize=16)
        page.insert_textbox(fitz.Rect(72, 100, 520, 780), body, fontsize=10)
    doc.save(str(path))


@pytest.fixture
def real_env(env, tmp_path, monkeypatch):
    """取回来的是一份真有文字层的 PDF；MineRU 用替身（可以让它慢、让它失败）。"""
    from tools import getpdf
    pdf = tmp_path / 'real.pdf'
    _real_pdf(pdf)

    def fetch(d, where=None):
        env['fetch'] += 1
        return {'doi': d, 'ok': True, 'reason': 'ok', 'path': str(pdf), 'title': '', 'landing': '', 'bytes': 1}
    monkeypatch.setattr(getpdf, 'fetch_one', fetch)
    return env


def test_快速层先出_MineRU后台补_不挡下载(real_env, monkeypatch):
    import threading
    gate = threading.Event()

    def slow_mineru(pdf_path, out_dir, reuse=True):
        gate.wait(5)                                   # MineRU 还在排队
        real_env['parse'] += 1
        io.open(os.path.join(out_dir, 'full.md'), 'w', encoding='utf-8').write('# T\n\n## 1. Introduction\n\nX\n')
        io.open(os.path.join(out_dir, 'layout.json'), 'w').write('{}')
        from shared.adapters import pdf_parse
        pdf_parse._tier_text_clear(out_dir)
    monkeypatch.setattr('shared.adapters.pdf_parse.parse_pdf', slow_mineru)
    up = F.Upgrader()
    r = F.one(DOI, upgrader=up)
    assert r['ok'] and r['code'] == F.OK and r['tier'] == 'text', 'PDF 到手几秒就该能读，不等 MineRU'
    assert r['route'] == 'browser_pdf' and r['stage'] == 'parse_text'
    assert real_env['parse'] == 0, 'MineRU 还在排队，结果已经回来了'
    gate.set()
    up.join()
    assert F.tier_of(r['id']) == 'structured', 'MineRU 成了就升级'


def test_MineRU失败_快速层照旧可用(real_env, monkeypatch):
    from shared.adapters import pdf_parse

    def boom(*a, **k):
        raise pdf_parse.PDFParseError('解析超时')
    monkeypatch.setattr('shared.adapters.pdf_parse.parse_pdf', boom)
    rs = F.many([DOI], gap=0)
    assert rs[0]['ok'] and rs[0]['tier'] == 'text' and rs[0]['chars'] > 1000, 'MineRU 超时不许让这篇变成 0 字'


def test_只查不取_本地有PDF就出快速层_不等MineRU(real_env, monkeypatch):
    import shutil
    from tools import getpdf
    pid = paths.paper_id_from_doi(DOI)
    os.makedirs(paths.paper_raw_dir(pid), exist_ok=True)
    shutil.copy(getpdf.fetch_one(DOI)['path'], paths.local_pdf(pid))
    real_env['fetch'] = 0
    monkeypatch.setattr('shared.adapters.pdf_parse.parse_pdf', lambda *a, **k: pytest.fail('只查不取不许等 MineRU'))
    r = F.one(DOI, allow_fetch=False)
    assert r['ok'] and r['tier'] == 'text' and real_env['fetch'] == 0


def test_状态码_每种失败各有各的码(env, monkeypatch):
    from tools import getpdf
    for reason, code, retry in (('captcha', F.CAPTCHA_REQUIRED, True), ('no_access', F.NOT_SUBSCRIBED, False),
                                ('no_pdf_link', F.NO_PDF_LINK, False), ('navigate_failed', F.NETWORK_ERROR, True),
                                # 2026-10-12：不是 PDF ≠ 验证码（Pleiades 一篇实为没订，被叫去点不存在的验证码）
                                ('not_pdf', F.NOT_PDF, False)):
        monkeypatch.setattr(getpdf, 'fetch_one', lambda d, where=None, _r=reason: {
            'doi': d, 'ok': False, 'reason': _r, 'path': '', 'bytes': 0})
        r = F.one(DOI)
        assert (r['code'], r['retryable'], r['stage']) == (code, retry, 'download'), reason
        assert r['why'], '中文原因照留'
    assert F.one('not-a-doi')['code'] == F.NOT_FOUND


def test_取的时候炸了_算网络错误_不抛(env, monkeypatch):
    from tools import getpdf

    def boom(d, where=None):
        raise RuntimeError('浏览器没开')
    monkeypatch.setattr(getpdf, 'fetch_one', boom)
    r = F.one(DOI)
    assert r['code'] == F.NETWORK_ERROR and r['retryable'] and '浏览器没开' in r['why']


def test_撞验证的出版商_同家暂缓_别家照跑(env, monkeypatch):
    """2026-10-02：Science 撞上验证，队列里下一篇 Wiley 一直等着。现在同家的先不敲，别家的照跑。"""
    monkeypatch.setattr(F, 'RETRY_COOLDOWN', 0)
    tried, warned = [], []

    def fake_one(doi, allow_fetch=True, upgrader=None):
        tried.append(doi)
        if doi.startswith('10.1126/'):
            return {'doi': doi, 'id': '', 'ok': False, 'code': F.CAPTCHA_REQUIRED, 'source': F.SRC_FETCH,
                    'why': 'captcha'}
        return {'doi': doi, 'id': '', 'ok': True, 'code': F.OK, 'source': F.SRC_FETCH, 'why': ''}
    monkeypatch.setattr(F, 'one', fake_one)
    rs = F.many(['10.1126/s1', '10.1126/s2', '10.1002/w1', '10.1126/s3'], gap=0, limit=4,
                notify=lambda t, b: warned.append(b))
    assert tried[:2] == ['10.1126/s1', '10.1002/w1'], 'Science 撞了，后面的 Science 先不敲，Wiley 照跑'
    assert sum(1 for d in tried if d.startswith('10.1126/')) == 2, '补试时这家只试一篇，还挡着就不再敲'
    by = {r['doi']: r for r in rs}
    assert by['10.1002/w1']['ok']
    assert all(by[d]['code'] == F.CAPTCHA_REQUIRED and by[d]['retryable'] for d in ('10.1126/s2', '10.1126/s3'))
    assert len(warned) == 1, '每家出版商只喊人一次'


def test_网断了_连着失败就先停手_歇够了补试(env, monkeypatch):
    """2026-10-12：doi.org 断了 18 分钟，10 篇不同出版商连着各等 90 秒，全报「找不到」（不可重试）。
    现在：连着 NET_TRIP 篇网络失败就不再去敲后面的，整批跑完歇一会儿统一补试；网好了就都拿到。"""
    monkeypatch.setattr(F, 'NET_COOLDOWN', 0)
    tried, down = [], {'on': True}

    def fake_one(doi, allow_fetch=True, upgrader=None):
        tried.append(doi)
        if down['on'] and doi != '10.1002/a0':
            return {'doi': doi, 'id': '', 'ok': False, 'code': F.NETWORK_ERROR, 'source': F.SRC_FETCH,
                    'why': 'navigate_failed'}
        return {'doi': doi, 'id': '', 'ok': True, 'code': F.OK, 'source': F.SRC_FETCH, 'why': ''}
    monkeypatch.setattr(F, 'one', fake_one)
    dois = ['10.1002/a0'] + ['10.%d/x%d' % (1016 + i, i) for i in range(7)]
    real_sleep = F.time.sleep
    monkeypatch.setattr(F.time, 'sleep', lambda s: down.update(on=False) if s == 0 else real_sleep(0))
    rs = F.many(dois, gap=0, limit=8)
    first = tried[:tried.index(dois[1]) + F.NET_TRIP]
    assert len(first) == 1 + F.NET_TRIP, '连着 %d 篇网络失败后就不再去敲后面的' % F.NET_TRIP
    assert all(r['ok'] for r in rs), '歇够了补试，网好了就都拿到'


def test_补试时网还没好_剩下的标网络错误可重试(env, monkeypatch):
    monkeypatch.setattr(F, 'NET_COOLDOWN', 0)
    tried = []

    def fake_one(doi, allow_fetch=True, upgrader=None):
        tried.append(doi)
        return {'doi': doi, 'id': '', 'ok': False, 'code': F.NETWORK_ERROR, 'retryable': True, 'source': F.SRC_FETCH,
                'why': 'navigate_failed'}
    monkeypatch.setattr(F, 'one', fake_one)
    dois = ['10.%d/x%d' % (1016 + i, i) for i in range(8)]
    rs = F.many(dois, gap=0, limit=8)
    assert len(tried) == F.NET_TRIP + 2, '第一轮敲 NET_TRIP 篇、补试再敲 2 篇就停'
    assert all(r['code'] == F.NETWORK_ERROR and r['retryable'] for r in rs)
