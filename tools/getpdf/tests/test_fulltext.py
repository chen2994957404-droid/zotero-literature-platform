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


def test_第三层_Zotero库里有就用它的编号也不下载(env, monkeypatch):
    """这篇在他自己库里 → **id 用 Zotero 编号**，跟已有的精读落在同一个目录。"""
    zpath = str(paths.RAW) + '/from_zotero.pdf'
    io.open(zpath, 'wb').write(b'%PDF-1.4 zotero copy')
    monkeypatch.setattr('shared.adapters.zotero_client.find_pdf', lambda k: zpath)
    monkeypatch.setattr('shared.adapters.zotero_client.find_si', lambda k: (None, None))
    r = F.one(DOI, zotero_index={DOI.lower(): 'AAAA1111'})
    assert r['id'] == 'AAAA1111' and r['in_zotero'] is True
    assert r['source'] == F.SRC_ZOTERO and env['fetch'] == 0
    assert os.path.exists(paths.local_pdf('AAAA1111')),         'Zotero 的附件要**复制成本地正本** —— 证据库是全集，Zotero 只是子集'
    from shared.kernel import catalog
    assert catalog.find(DOI) == 'AAAA1111', '落地后目录里就该查得到'


def test_不许取时只走前三层(env):
    r = F.one(DOI, allow_fetch=False)
    assert not r['ok'] and env['fetch'] == 0
    assert '不允许' in r['why']


def test_取失败不抛异常_把原因说清楚(env, monkeypatch):
    from tools import getpdf
    monkeypatch.setattr(getpdf, 'fetch_one', lambda d, where=None: {
        'doi': d, 'ok': False, 'reason': 'paywall', 'path': '', 'bytes': 0})
    r = F.one(DOI)
    assert r['ok'] is False and r['why'] and env['parse'] == 0


class Test批量:
    def test_默认最多三篇_批量留给人点(self, env):
        dois = ['10.1021/a%d' % i for i in range(6)]
        rs = F.many(dois, gap=0)
        assert len(rs) == 3, '模型不知道整机构 IP 被封的代价有多重'

    def test_命中缓存的不占礼貌间隔(self, env, monkeypatch):
        """20 秒间隔是为了不敲坏出版商 —— 没敲它就不该等。"""
        slept = []
        monkeypatch.setattr('time.sleep', lambda s: slept.append(s))
        F.one(DOI)                      # 先把第一篇做进缓存
        F.many([DOI, '10.1021/b'], gap=20)
        assert slept == [], '第一篇走的是缓存，不该为它等 20 秒'

    def test_进度文件边跑边写(self, env, tmp_path):
        p = str(tmp_path / 'progress.json')
        F.many([DOI], gap=0, progress=p)
        import json
        d = json.load(io.open(p, encoding='utf-8'))
        assert d['done'] is True and d['finished'] == 1
        assert d['results'][0]['id']


def test_摘要里说清楚每篇是怎么来的(env):
    rs = F.many([DOI], gap=0)
    txt = F.summarize(rs)
    assert '刚去取的' in txt and 'library_section' in txt, '要告诉模型下一步怎么读'
    assert '菜单' in txt and '全文 48 字符' in txt, '做完直接把菜单带回来，模型少一次调用（2026-09-14）'


def test_命令行的参数顺序(monkeypatch):
    """位置参数必须在选项**前面**（`shared.kernel.cli` 的约定）。

    第一次真跑时把顺序写成 `--fulltext <DOI>`，`positionals()` 在第一个 `--`
    就停了，于是拿到空列表 —— **不报错，只是安静地什么都不做**。
    MCP 后台那条路拼的是同一个命令，一起错。
    """
    from shared.kernel import cli
    monkeypatch.setattr(cli, '_argv', lambda: ['10.1002/pat.70289', '--fulltext'])
    assert cli.positionals() == ['10.1002/pat.70289']
    monkeypatch.setattr(cli, '_argv', lambda: ['--fulltext', '10.1002/pat.70289'])
    assert cli.positionals() == [], '写反了就是空的 —— 这就是那次空跑的原因'


# ── SI 顺手解析（2026-09-30：落地流水线停了，取全文拿到的 si.pdf 一直没人解析）──────

def _put_si(pid):
    os.makedirs(paths.paper_raw_dir(pid), exist_ok=True)
    io.open(paths.local_si(pid, 'pdf'), 'wb').write(b'%PDF-1.4 si')


def test_SI原件在就一起解析(env, monkeypatch):
    seen = []
    def fake_doc(src, out_dir, reuse=True):
        seen.append(src)
        os.makedirs(out_dir, exist_ok=True)
        io.open(os.path.join(out_dir, 'full.md'), 'w', encoding='utf-8').write('# SI\n\nDFT B3LYP.\n')
    monkeypatch.setattr('shared.adapters.pdf_parse.parse_document', fake_doc)
    pid = paths.paper_id_from_doi(DOI)
    _put_si(pid)
    r = F.one(DOI)
    assert r['ok'] and r['si'] == 'parsed' and len(seen) == 1
    assert F.one(DOI)['si'] == 'parsed' and len(seen) == 1, '解析过的 SI 不重复解析'


def test_只查不取时不解析SI(env, monkeypatch):
    monkeypatch.setattr('shared.adapters.pdf_parse.parse_document',
                        lambda *a, **k: pytest.fail('只查不取不许花解析额度'))
    pid = paths.paper_id_from_doi(DOI)
    os.makedirs(os.path.dirname(paths.fulltext(pid)), exist_ok=True)
    io.open(paths.fulltext(pid), 'w', encoding='utf-8').write('# T\n')
    _put_si(pid)
    assert F.one(DOI, allow_fetch=False)['si'] == 'unparsed'


def test_没有SI就说没有(env):
    assert F.one(DOI)['si'] == 'none'


def test_正文早有SI缺_再要这篇时去补SI(env, monkeypatch):
    F.one(DOI)                                   # 第一次：正文到手，SI 没取成（替身回 no_si）
    from shared.kernel import catalog
    pid = paths.paper_id_from_doi(DOI)
    catalog.clear_si_none(pid)                   # 假设那次的「没有 SI」是误判，撤回
    got = []
    from tools import getpdf
    monkeypatch.setattr(getpdf, 'fetch_si_one', lambda d, where=None: got.append(d) or {
        'doi': d, 'ok': False, 'reason': 'captcha', 'path': '', 'bytes': 0})
    r = F.one(DOI)
    assert r['source'] == F.SRC_CACHE and got == [DOI], '缓存命中也该去补缺的 SI'


def test_确认没有SI的不再去敲(env, monkeypatch):
    F.one(DOI)                                   # 替身回 no_si → 记成「确认没有」
    from tools import getpdf
    monkeypatch.setattr(getpdf, 'fetch_si_one', lambda *a, **k: pytest.fail('确认没有的不许再敲出版商'))
    assert F.one(DOI)['source'] == F.SRC_CACHE


def test_撞上人机验证的整批跑完后补试一次(env, monkeypatch):
    from shared.adapters import pdf_fetch
    monkeypatch.setattr(F, 'RETRY_COOLDOWN', 0)
    tries = {}
    real_one = F.one
    def flaky(doi, zotero_index=None, allow_fetch=True, use_zotero=True, upgrader=None):
        tries[doi] = tries.get(doi, 0) + 1
        if doi.endswith('/b') and tries[doi] == 1:
            return {'doi': doi, 'id': '', 'ok': False, 'source': F.SRC_FETCH, 'secs': 0, 'chars': 0,
                    'why': '正文没取到 —— ' + pdf_fetch.REASONS['captcha']}
        if doi.endswith('/c'):
            return {'doi': doi, 'id': '', 'ok': False, 'source': F.SRC_FETCH, 'secs': 0, 'chars': 0,
                    'why': '正文没取到 —— ' + pdf_fetch.REASONS['no_access']}
        return real_one(doi, zotero_index, allow_fetch, use_zotero, upgrader)
    monkeypatch.setattr(F, 'one', flaky)
    rs = F.many(['10.1021/a', '10.1021/b', '10.1021/c'], gap=0, limit=3)
    assert [r['ok'] for r in rs] == [True, True, False]
    assert tries == {'10.1021/a': 1, '10.1021/b': 2, '10.1021/c': 1}, '只有被验证挡住的才补试，没权限的不白敲'


def test_不碰Zotero那条路_一次都不问Zotero(env, monkeypatch):
    """2026-09-30 用户定：Claude Science 那条路不跟 Zotero 扯上关系 —— 只认证据库正本和出版商。"""
    from tools import getpdf
    monkeypatch.setattr(getpdf, 'doi_index', lambda *a, **k: pytest.fail('不许问 Zotero 的 DOI 索引'))
    monkeypatch.setattr('shared.adapters.zotero_client.find_pdf', lambda *a, **k: pytest.fail('不许去 Zotero 找正文附件'))
    monkeypatch.setattr('shared.adapters.zotero_client.find_si', lambda *a, **k: pytest.fail('不许去 Zotero 找 SI 附件'))
    from shared.kernel import catalog
    zkey = 'ZOTK1234'                                 # 一篇 id 恰好是 Zotero 编号的老文献（证据库里有目录、没正本）
    catalog.register(zkey, doi=DOI)
    rs = F.many([DOI], gap=0, use_zotero=False)
    assert rs[0]['ok'] and rs[0]['source'] == F.SRC_FETCH, '不找 Zotero 就直接去出版商取'


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
                                ('no_pdf_link', F.NO_PDF_LINK, False), ('navigate_failed', F.NOT_FOUND, False)):
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

    def fake_one(doi, zotero_index=None, allow_fetch=True, use_zotero=True, upgrader=None):
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
