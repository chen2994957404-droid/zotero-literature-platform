# -*- coding: utf-8 -*-
"""core.jobs 的离线测试 —— 全部用临时库，绝不碰真实的 workflow_data/state.db。

这些断言就是状态库的契约本身：
「只补缺的部分」「升级即查询」「状态库坏了也不许拖垮主流程」这三条承诺，
在这里各有一条测试钉死。
"""
import os
import sqlite3

import pytest

from core import jobs, paths

KEY = 'ABCD1234'
KEY2 = 'EFGH5678'


@pytest.fixture
def db(tmp_path, monkeypatch):
    """把状态库指到临时目录，并保证测试之间互不串味。"""
    p = str(tmp_path / 'state.db')
    monkeypatch.setattr(jobs, 'db_path', lambda: p)
    jobs.close()
    yield p
    jobs.close()


def test_状态库路径走数据契约():
    assert jobs.db_path() == paths.state_db()
    assert paths.state_db().endswith('state.db')


def test_一次成功的执行会被完整记录(db):
    with jobs.track(KEY, 'main_summary', model='deepseek-v4-flash',
                    prompt_ver=2) as run:
        run.note(cost=0.12)
    row = jobs.last(KEY, 'main_summary')
    assert row['status'] == jobs.OK
    assert row['model'] == 'deepseek-v4-flash'
    assert row['prompt_ver'] == 2
    assert row['cost'] == pytest.approx(0.12)
    assert row['finished_at'] >= row['started_at']


def test_抛异常时记为失败且异常照样往上抛(db):
    """状态库负责记录发生了什么，不负责改变发生了什么。"""
    with pytest.raises(ValueError):
        with jobs.track(KEY, 'parse'):
            raise ValueError('MineRU 挂了')
    row = jobs.last(KEY, 'parse')
    assert row['status'] == jobs.FAILED
    assert 'MineRU 挂了' in row['error']


def test_只补缺的部分_产物在不在是第一判据(db, monkeypatch):
    """真相在硬盘上：状态库说做完了，但产物没了，就得判定为没做完。"""
    present = {'summary': True}
    monkeypatch.setattr(paths, 'has', lambda k, what: present.get(what, False))

    with jobs.track(KEY, 'main_summary'):
        pass
    assert jobs.is_done(KEY, 'main_summary', require='summary')

    present['summary'] = False
    assert not jobs.is_done(KEY, 'main_summary', require='summary')


def test_状态库上线前做过的东西不会被判成没做(db, monkeypatch):
    """老数据没有执行记录，但产物在 —— 必须认它，否则一上线就要全库重跑。"""
    monkeypatch.setattr(paths, 'has', lambda k, what: True)
    assert jobs.last(KEY2, 'main_summary') is None
    assert jobs.is_done(KEY2, 'main_summary', require='summary')


def test_上次失败的不算做完(db, monkeypatch):
    monkeypatch.setattr(paths, 'has', lambda k, what: True)
    rid = jobs.start(KEY, 'si_summary')
    jobs.fail(rid, 'timeout')
    assert not jobs.is_done(KEY, 'si_summary', require='si_summary')


def test_升级即查询_版本落后的自动进重跑清单(db, monkeypatch):
    monkeypatch.setattr(paths, 'has', lambda k, what: True)
    with jobs.track(KEY, 'main_summary', prompt_ver=2):
        pass
    with jobs.track(KEY2, 'main_summary', prompt_ver=3):
        pass

    assert jobs.is_done(KEY, 'main_summary', require='summary', prompt_ver=2)
    assert not jobs.is_done(KEY, 'main_summary', require='summary', prompt_ver=3)
    assert jobs.stale('main_summary', prompt_ver=3) == [KEY]
    assert jobs.stale('main_summary', prompt_ver=2) == []


def test_重跑清单只看每篇最后一次(db):
    """先失败后成功的，不该还挂在待重跑清单里。"""
    jobs.fail(jobs.start(KEY, 'parse'), 'boom')
    with jobs.track(KEY, 'parse'):
        pass
    assert jobs.stale('parse') == []


def test_进度统计与卡住的执行(db):
    with jobs.track(KEY, 'parse'):
        pass
    jobs.start(KEY2, 'parse')          # 只 start 不 finish = 进程被杀的样子
    assert jobs.summary('parse') == {'parse': {jobs.OK: 1, jobs.RUNNING: 1}}
    assert [r['item_key'] for r in jobs.running()] == [KEY2]
    assert jobs.running(older_than=3600) == []


def test_非法key当场拒绝(db):
    with pytest.raises(paths.BadKeyError):
        jobs.start('这不是key', 'parse')


def test_状态库坏了也不许拖垮主流程(db, monkeypatch):
    """磁盘满、库被锁、文件损坏 —— 记不上账可以，精读白做不行。"""
    def boom(*a, **kw):
        raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr(jobs, 'connect', boom)

    assert jobs.start(KEY, 'parse') is None       # 不抛
    jobs.finish(1, jobs.OK)                       # 不抛
    assert jobs.last(KEY, 'parse') is None
    assert jobs.history(KEY) == []
    with jobs.track(KEY, 'parse'):                # 主流程照跑
        pass


def test_状态库文件是可重建的产物而不是资产(db):
    """删掉重建必须能用 —— 这是「它只是索引」这句话的可执行版本。"""
    with jobs.track(KEY, 'parse'):
        pass
    jobs.close()
    os.remove(db)
    assert jobs.history(KEY) == []
    with jobs.track(KEY, 'parse'):
        pass
    assert jobs.last(KEY, 'parse')['status'] == jobs.OK
