# -*- coding: utf-8 -*-
"""落地流水线：**有正本就自动解析 + 骨架，做过的一步都不重做**（2026-09-13）。

全离线：MineRU 换成假替身，向量库关掉。测的是编排，不是解析器。
"""
import io
import os

import pytest

from shared.kernel import catalog, paths
from host import ingest

DOI = '10.1021/acs.macromol.5b00210'


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ('RAW', 'CURATED', 'SERVING', 'STATE'):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(paths, name, str(d))
    monkeypatch.setattr(paths, 'STRUCTURED', str(tmp_path / 'serving' / 'structured'))
    # 单实例锁也指到临时目录：主力机上 watcher 正抱着真实的 ingest 锁，
    # 测试会「让开」而一篇不做（2026-09-14 部署时体检就这么红过一次）
    from shared.kernel import proc_lock
    monkeypatch.setattr(proc_lock, 'LOCK_DIR', str(tmp_path / 'locks'))
    calls = {'parse': 0}

    def fake_parse(pdf_path, out_dir, reuse=True):
        calls['parse'] += 1
        os.makedirs(out_dir, exist_ok=True)
        io.open(os.path.join(out_dir, 'full.md'), 'w', encoding='utf-8').write(
            '# T\n\n## 1. Introduction\n\nbla\n\n## 2. Results\n\nTensile strength 12 MPa.\n')
        io.open(os.path.join(out_dir, 'layout.json'), 'w').write('{}')

    monkeypatch.setattr('shared.adapters.pdf_parse.parse_pdf', fake_parse)

    def fake_units(pid, model, log=print, sample_model=None):     # 单元库那步要本地大模型；编程端没有 → 0 条会被当失败，这里装作抽到了
        calls['units'] = calls.get('units', 0) + 1
        io.open(paths.units(pid), 'w', encoding='utf-8').write('{"units": [1]}')
        return 1, paths.units(pid)

    monkeypatch.setattr('tools.extract.fine_fact.extract_to_store', fake_units)
    monkeypatch.setattr('tools.extract.fine_action.extract_to_store', fake_units)

    def fake_profile(pid, model, log=print):
        io.open(paths.profile(pid), 'w', encoding='utf-8').write('{"type": "synthesis"}')
        return {'type': 'synthesis', 'source': 'model'}

    monkeypatch.setattr('tools.deepread.profile.classify_to_store', fake_profile)
    return calls


def _land(pid):
    os.makedirs(os.path.dirname(paths.local_pdf(pid)), exist_ok=True)
    io.open(paths.local_pdf(pid), 'wb').write(b'%PDF-1.4 fake')
    catalog.register(pid, doi=DOI, title='T')


def test_有正本没解析的算积压_做完就不再是(env):
    pid = paths.paper_id_from_doi(DOI)
    _land(pid)
    assert ingest.backlog() == [pid]
    c = ingest.run_backlog(with_vectors=False, say=lambda s: None)
    assert c['parsed'] == 1 and c['outlined'] == 1 and c['failed'] == 0
    assert os.path.isfile(paths.fulltext(pid)) and os.path.isfile(paths.outline(pid))
    assert ingest.backlog() == [], '做完了就不该再出现在积压里'


def test_幂等_第二遍一次解析都不花(env):
    pid = paths.paper_id_from_doi(DOI)
    _land(pid)
    ingest.run_backlog(with_vectors=False, say=lambda s: None)
    env['parse'] = 0
    r = ingest.ingest_one(pid, say=lambda s: None)
    assert env['parse'] == 0, '解析过的再解析 = 白花 MineRU 额度'
    assert r['main'] == 'skip' and r['outline'] == 'skip'


def test_docx的SI直接读字不走MineRU(env, monkeypatch):
    pid = paths.paper_id_from_doi(DOI)
    _land(pid)
    io.open(paths.local_si(pid, 'docx'), 'wb').write(b'PK fake docx')
    def fake_docx(path, out_dir, reuse=True):
        os.makedirs(out_dir, exist_ok=True)
        io.open(os.path.join(out_dir, 'full.md'), 'w', encoding='utf-8').write('Synthesis: 1.0 g boric acid')
        return out_dir
    monkeypatch.setattr('shared.adapters.pdf_parse.parse_docx', fake_docx)
    r = ingest.ingest_one(pid, say=lambda s: None)
    assert r['si'] == 'done' and env['parse'] == 1, 'docx 不该占一次 MineRU'
    assert 'boric acid' in io.open(paths.si_fulltext(pid), encoding='utf-8').read()


def test_解析失败不抛异常_也不吞掉(env, monkeypatch):
    pid = paths.paper_id_from_doi(DOI)
    _land(pid)
    monkeypatch.setattr('shared.adapters.pdf_parse.parse_pdf',
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('quota')))
    r = ingest.ingest_one(pid, say=lambda s: None)
    assert r['main'].startswith('fail') and r['outline'] == 'skip'
    assert [f[0] for f in ingest.failures()] == [pid], '没做成的要能被人看见，隔天再试'


def test_刚失败过的先不重试_隔一天再试(env, monkeypatch):
    """MineRU 拒收的超长 PDF 曾让 watcher 每分钟白敲一次（2026-09-14）。"""
    from shared.kernel import jobs
    pid = paths.paper_id_from_doi(DOI)
    _land(pid)
    monkeypatch.setattr('shared.adapters.pdf_parse.parse_pdf',
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('exceeds limit (200 pages)')))
    ingest.ingest_one(pid, say=lambda s: None)
    assert ingest.backlog() == [], '刚失败的不该立刻回到积压里'
    assert ingest.failures() and ingest.failures()[0][0] == pid
    monkeypatch.setattr(ingest, 'RETRY_AFTER', 0)
    assert ingest.backlog() == [pid], '过了重试间隔要再试'
