# -*- coding: utf-8 -*-
"""检索台账（2026-09-26）：记账、按条判断、饱和曲线、捕获–再捕获、挖新词。全离线。"""
import pytest

from shared.kernel import paths
from tools.litsearch import session as S


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, 'STATE', str(tmp_path / 'state'))


def _it(doi, title, abstract='', **kw):
    d = {'doi': doi, 'title': title, 'abstract': abstract, 'year': 2025}
    d.update(kw)
    return d


def test_建会话_判据替换_范围约定追加():
    s = S.open_session('q1', question='剪切硬化用了什么新动态键', criteria=['剪切硬化', '动态键'])
    assert s['criteria'] == ['剪切硬化', '动态键'] and s['round'] == 1
    S.open_session('q1', question='别的问题', criteria=['剪切硬化', '动态键', '2023 年后'], scope_note='应用类不算')
    s = S.open_session('q1')
    assert s['question'] == '剪切硬化用了什么新动态键', '问题只在原来为空时写入'
    assert len(s['criteria']) == 3 and s['scope_notes'][0]['note'] == '应用类不算'


def test_记账返回记账前状态_跨渠道累加():
    a, b = _it('10.1/A', 'Alpha gel'), _it('https://doi.org/10.1/B', 'Beta gel')
    st = S.record('q', 'keyword', [a, b], term='gel', total=100)
    assert [x['new'] for x in st] == [True, True]
    st = S.record('q', 'semantic', [_it('10.1/b', 'Beta gel'), _it('', 'No doi thing')], calls=3)
    assert st[0]['new'] is False and st[0]['channels'] == ['keyword'], 'DOI 大小写 / 前缀归一后是同一篇'
    assert st[1]['new'] is True
    w = S.open_session('q')['works']
    assert w['10.1/b']['channels'] == ['keyword', 'semantic']
    assert 'title:no doi thing' in w
    assert S.status('q')['n_calls'] == 4


def test_判断_中文别名_按条_默认依据():
    S.record('q', 'keyword', [_it('10.1/a', 'A', 'has abstract'), _it('10.1/b', 'B')])
    r = S.judge('q', [
        {'doi': '10.1/A', 'verdict': '相关', 'criteria': {'剪切硬化': '是', '动态键': True}},
        {'doi': '10.1/b', 'verdict': 'partial'},
        {'doi': '10.9/nope', 'verdict': 'relevant'},
        {'doi': '10.1/a', 'verdict': '也许吧'},
    ])
    assert r['judged'] == 2 and r['unknown'] == ['10.9/nope'] and r['bad'] == ['10.1/a']
    w = S.open_session('q')['works']
    j = w['10.1/a']['judgment']
    assert j['verdict'] == 'relevant' and j['criteria'] == {'剪切硬化': 'yes', '动态键': 'yes'}
    assert j['basis'] == 'abstract'
    assert w['10.1/b']['judgment']['basis'] == 'title', '没摘要默认记「仅标题」'
    st = S.status('q')
    assert st['n_relevant'] == 2 and st['relevant_title_only'] == 1


def test_饱和曲线按轮按首次渠道():
    S.record('q', 'keyword', [_it('10.1/a', 'A'), _it('10.1/b', 'B')])
    S.judge('q', [{'doi': '10.1/a', 'verdict': 'relevant'}])
    S.next_round('q')
    S.record('q', 'semantic', [_it('10.1/a', 'A'), _it('10.1/c', 'C')])
    S.judge('q', [{'doi': '10.1/c', 'verdict': 'relevant'}])
    S.next_round('q')
    S.record('q', 'cited_by', [_it('10.1/a', 'A')])
    curve = S.status('q')['curve']
    assert [r['new_relevant'] for r in curve] == [1, 1, 0], '第 3 轮没有新的相关 = 饱和信号'
    assert curve[1]['by_channel'] == {'semantic': {'new': 1, 'relevant': 1}}


def test_捕获再捕获只拿引用对文本():
    txt = [_it('10.1/%d' % i, 'T%d' % i) for i in range(6)]
    S.record('q', 'keyword', txt[:4])
    S.record('q', 'semantic', txt[3:])
    S.record('q', 'cited_by', [txt[0], txt[1], txt[5], _it('10.1/x', 'X')])
    S.judge('q', [{'doi': d['doi'], 'verdict': 'relevant'} for d in txt + [_it('10.1/x', 'X')]])
    cr = S.status('q')['capture_recapture']
    assert cr['text'] == 6 and cr['citation'] == 4 and cr['both'] == 3 and cr['reliable']
    assert cr['estimated_total'] == pytest.approx(S.chapman(6, 4, 3), abs=0.1)
    st = S.status('q')
    assert st['relevant_only_by_channel'].get('cited_by') == 1


def test_相对召回():
    S.record('q', 'keyword', [_it('10.1/a', 'A'), _it('10.1/b', 'B')])
    S.judge('q', [{'doi': '10.1/a', 'verdict': 'relevant'}])
    rr = S.status('q', benchmark=['10.1/A', '10.1/b', '10.1/c'])['relative_recall']
    assert rr['found_anywhere'] == 2 and rr['judged_relevant'] == 1 and rr['missing'] == ['10.1/c']


def test_挖新词_排除搜过的_没判相关时如实为空():
    docs = [_it('10.1/%d' % i, 'Boronic ester crosslinked network %d' % i,
                'dynamic boronic ester bonds give shear stiffening', first_author='Li', venue='Macromolecules')
            for i in range(3)]
    noise = [_it('10.2/%d' % i, 'Protective fabric composite %d' % i, 'kevlar fabric impact test')
             for i in range(5)]
    S.record('q', 'keyword', docs + noise, term='"shear stiffening"')
    assert S.mine_terms('q')['terms'] == []
    S.judge('q', [{'doi': d['doi'], 'verdict': 'relevant'} for d in docs])
    m = S.mine_terms('q')
    terms = [t['term'] for t in m['terms']]
    assert any('boronic ester' in t for t in terms)
    assert not any(t == 'shear stiffening' for t in terms), '搜过的词不再推荐'
    assert not any('fabric' in t for t in terms)
    assert m['authors'] == [('Li', 3)] and m['venues'] == [('Macromolecules', 3)]


def test_同一篇的多个DOI并成一条_别名也能判():
    t = 'Selective hydrogenolysis of polyethylene into liquid alkanes over ruthenium catalysts'
    S.record('q', 'keyword', [_it('10.1021/main', t)])
    st = S.record('q', 'semantic', [_it('10.2139/ssrn.123', t + '.'), _it('10.1/short', 'Editorial')])
    assert st[0]['new'] is False, '同标题（≥40 字）的另一个 DOI 算同一篇'
    w = S.open_session('q')['works']
    assert set(w) == {'10.1021/main', '10.1/short'} and w['10.1021/main']['aliases'] == ['10.2139/ssrn.123']
    assert w['10.1021/main']['channels'] == ['keyword', 'semantic']
    assert S.judge('q', [{'doi': '10.2139/ssrn.123', 'verdict': 'relevant'}])['judged'] == 1
    S.record('q', 'keyword', [_it('10.1/other', 'Editorial')])
    assert '10.1/other' in S.open_session('q')['works'], '短标题不合并（容易撞）'


def test_待判队列按轮次一批批给():
    S.record('q', 'keyword', [_it('10.1/%d' % i, 'T%d' % i, 'abs') for i in range(5)])
    S.next_round('q')
    S.record('q', 'semantic', [_it('10.2/x', 'X')])
    batch, left = S.pending('q', n=3)
    assert [b['doi'] for b in batch] == ['10.1/0', '10.1/1', '10.1/2'] and left == 3
    S.judge('q', [{'doi': b['doi'], 'verdict': 'irrelevant'} for b in batch])
    batch, left = S.pending('q', n=10)
    assert [b['doi'] for b in batch] == ['10.1/3', '10.1/4', '10.2/x'] and left == 0


def test_没判完或腿没走全就不能说饱和():
    S.record('q', 'keyword', [_it('10.1/a', 'A')])
    S.judge('q', [{'doi': '10.1/a', 'verdict': 'relevant'}])
    S.next_round('q')
    S.record('q', 'keyword', [_it('10.1/b', 'B')])
    sat = S.status('q')['saturation']
    assert not sat['can_claim'] and any('没判' in w for w in sat['why']) and any('没走' in w for w in sat['why'])
    S.record('q', 'semantic', [])
    S.record('q', 'cited_by', [])
    S.judge('q', [{'doi': '10.1/b', 'verdict': 'irrelevant'}])
    assert S.status('q')['saturation']['can_claim'] is True


def test_体检_相关比例可疑_分支没货():
    S.open_session('q', criteria=['c1'], branches=['vitrimer 化', '化学升级回收'])
    items = [_it('10.1/%d' % i, 'T%d' % i) for i in range(40)]
    S.record('q', 'keyword', items)
    S.judge('q', [{'doi': d['doi'], 'verdict': 'relevant', 'branch': 'vitrimer 化'} for d in items])
    st = S.status('q')
    assert any('可疑' in n for n in st['audit'])
    assert any('没有逐条填判据' in n for n in st['audit'])
    assert st['by_branch'] == {'vitrimer 化': 40, '化学升级回收': 0}
    assert any('化学升级回收' in n for n in st['audit'])


def test_按分支挖词():
    a = [_it('10.1/a%d' % i, 'Vitrimer polyethylene exchange %d' % i, 'boronic ester vitrimer network') for i in range(3)]
    b = [_it('10.1/b%d' % i, 'Hydrogenolysis ruthenium catalyst %d' % i, 'ruthenium hydrogenolysis liquid alkanes')
         for i in range(3)]
    S.record('q', 'keyword', a + b)
    S.judge('q', [{'doi': d['doi'], 'verdict': 'relevant', 'branch': 'v'} for d in a]
            + [{'doi': d['doi'], 'verdict': 'relevant', 'branch': 'c'} for d in b])
    terms = ' '.join(t['term'] for t in S.mine_terms('q', branch='c')['terms'])
    assert 'hydrogenolysis' in terms and 'vitrimer' not in terms
