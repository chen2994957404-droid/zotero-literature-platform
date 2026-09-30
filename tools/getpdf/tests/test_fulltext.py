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
    def flaky(doi, zotero_index=None, allow_fetch=True):
        tries[doi] = tries.get(doi, 0) + 1
        if doi.endswith('/b') and tries[doi] == 1:
            return {'doi': doi, 'id': '', 'ok': False, 'source': F.SRC_FETCH, 'secs': 0, 'chars': 0,
                    'why': '正文没取到 —— ' + pdf_fetch.REASONS['captcha']}
        if doi.endswith('/c'):
            return {'doi': doi, 'id': '', 'ok': False, 'source': F.SRC_FETCH, 'secs': 0, 'chars': 0,
                    'why': '正文没取到 —— ' + pdf_fetch.REASONS['no_access']}
        return real_one(doi, zotero_index, allow_fetch)
    monkeypatch.setattr(F, 'one', flaky)
    rs = F.many(['10.1021/a', '10.1021/b', '10.1021/c'], gap=0, limit=3)
    assert [r['ok'] for r in rs] == [True, True, False]
    assert tries == {'10.1021/a': 1, '10.1021/b': 2, '10.1021/c': 1}, '只有被验证挡住的才补试，没权限的不白敲'
