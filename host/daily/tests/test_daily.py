# -*- coding: utf-8 -*-
"""每日作业的接线测试：四步按顺序做、一步挂了不拖累后面、取件数受上限约束。全部离线（假的 journalwatch / getpdf）。"""
import types

import pytest

from shared.kernel import heartbeat
from host import daily


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setattr(heartbeat.paths, 'runtime', lambda name, **kw: str(tmp_path / name))
    calls = []
    jw = types.SimpleNamespace(
        patrol=lambda **kw: (calls.append('patrol') or
                             {'n_journals': 3, 'items': [{'passes': True}, {'passes': False}], 'failed': []}),
        fill_abstracts=lambda **kw: (calls.append('abstracts') or (5, 9)),
        fill_from_s2=lambda **kw: (calls.append('s2') or (2, 4)),
        fill_topics=lambda **kw: (calls.append('topics') or (1, 1)),
        enqueue_passing=lambda items: (calls.append('enqueue') or 1),
        enqueue_recent=lambda **kw: 2,
        next_to_harvest=lambda n: [(f'10.1/{i}', {'title': f't{i}', 'venue': 'v'}) for i in range(n)],
        mark_harvest=lambda doi, ok, note: calls.append(('mark', doi, ok)),
    )
    gp = types.SimpleNamespace(land=lambda doi, with_si=True: (calls.append(('land', doi)) or {'ok': doi.endswith('0')}))
    import tools
    monkeypatch.setattr(tools, 'journalwatch', jw, raising=False)
    monkeypatch.setattr(tools, 'getpdf', gp, raising=False)
    return jw, gp, calls


def test_四步按顺序做且取件不超上限(fake, monkeypatch):
    jw, gp, calls = fake
    monkeypatch.setattr(daily, 'HARVEST_PER_DAY', 3)
    r = daily.run(say=lambda *a: None)
    order = [c for c in calls if isinstance(c, str)]
    assert order == ['patrol', 'abstracts', 's2', 'topics', 'enqueue']
    assert sum(1 for c in calls if c[0] == 'land') == 3
    assert r == {'new': 2, 'queued': 3, 'harvested': 1, 'todo': 3}
    # 每篇取件的结果都记回雷达库（取不到的隔天再试全靠这个）
    assert sum(1 for c in calls if c[0] == 'mark') == 3
    # 做完要报 done，否则面板 20 分钟后把它当「卡住」
    assert heartbeat.age(daily.BEACON, heartbeat.DONE) is not None


def test_补摘要挂了不拖累取件(fake, monkeypatch):
    jw, gp, calls = fake
    def boom(**kw):
        raise RuntimeError('S2 429')
    jw.fill_from_s2 = boom
    monkeypatch.setattr(daily, 'HARVEST_PER_DAY', 1)
    said = []
    r = daily.run(say=said.append)
    assert r['todo'] == 1 and any(c[0] == 'land' for c in calls)
    assert any('补摘要失败' in m for m in said)


def test_单篇取件抛异常也记失败并继续(fake, monkeypatch):
    jw, gp, calls = fake
    def land(doi, with_si=True):
        if doi.endswith('0'):
            raise TimeoutError('浏览器挂了')
        return {'ok': True}
    gp.land = land
    monkeypatch.setattr(daily, 'HARVEST_PER_DAY', 2)
    r = daily.run(say=lambda *a: None)
    marks = [c for c in calls if c[0] == 'mark']
    assert [m[2] for m in marks] == [False, True]
    assert r['harvested'] == 1
