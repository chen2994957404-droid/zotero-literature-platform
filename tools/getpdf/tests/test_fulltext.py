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

    monkeypatch.setattr(F, '_fetch_one', fake_fetch)
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
    r = F.one(DOI, zotero_index={DOI.lower(): 'AAAA1111'})
    assert r['id'] == 'AAAA1111' and r['in_zotero'] is True
    assert r['source'] == F.SRC_ZOTERO and env['fetch'] == 0


def test_不许取时只走前三层(env):
    r = F.one(DOI, allow_fetch=False)
    assert not r['ok'] and env['fetch'] == 0
    assert '不允许' in r['why']


def test_取失败不抛异常_把原因说清楚(env, monkeypatch):
    monkeypatch.setattr(F, '_fetch_one', lambda d: {
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
    assert '刚去取的' in txt and 'library_outline' in txt, '要告诉模型下一步怎么读'


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
