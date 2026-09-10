# -*- coding: utf-8 -*-
"""合集路径解析的守卫（2026-09-10 加）。

**为什么值得单独测**：这个函数是被一次「假汇报」逼出来的。
`stash` 原来只会归进固定的「LLM导入/建库用」，用户说「收进阿课题下的某某文件夹」时
外部 agent 没有入口，于是去调底层接口 —— 失败之后**给失败编了一套
「跨账号安全隔离机制」的解释**，而那个机制根本不存在。

所以这里测的重点不只是「能不能解析对」，还有**失败时说的话对不对**：
报错必须把那一层实际有什么列出来，让调用方照着改，而不是自由发挥。
"""
import pytest

from tools import getpdf


class _假的Web:
    """够用的假 _web：只实现 resolve_collection 会碰的三个函数。"""

    def __init__(self, cols):
        self._cols = cols
        self.建过 = []

    def list_collections(self, limit=100):
        return self._cols

    def find_collection(self, name, parent_key=None, cols=None):
        for c in (cols or self._cols):
            d = c['data']
            if d['name'] == name and (d.get('parentCollection') or None) == (parent_key or None):
                return c['key']
        return None

    def ensure_collection(self, name, parent_key=None, action='', force=False, cols=None):
        hit = self.find_collection(name, parent_key, cols)
        if hit:
            return hit
        key = f'NEW{len(self.建过)}'
        self.建过.append((name, parent_key))
        self._cols.append({'key': key,
                           'data': {'name': name, 'parentCollection': parent_key or False}})
        return key


def _col(key, name, parent=False):
    return {'key': key, 'data': {'name': name, 'parentCollection': parent}}


@pytest.fixture
def 假库(monkeypatch):
    cols = [_col('BJVQSCA8', '阿课题'),
            _col('ZI6BPX6V', '剪切硬化材料', 'BJVQSCA8'),
            _col('CTJZME6B', '抗冲击', 'BJVQSCA8'),
            _col('TJ6W8HXF', '1-聚硼硅氧烷与剪切变硬体系', 'CTJZME6B'),
            _col('XA5PD2GU', '专利')]
    fake = _假的Web(cols)
    import shared.adapters.zotero_client._web as W
    for fn in ('list_collections', 'find_collection', 'ensure_collection'):
        monkeypatch.setattr(W, fn, getattr(fake, fn))
    return fake


def test_已有的路径直接解析成key(假库):
    assert getpdf.resolve_collection('阿课题/抗冲击') == 'CTJZME6B'
    assert getpdf.resolve_collection('阿课题/抗冲击/1-聚硼硅氧烷与剪切变硬体系') == 'TJ6W8HXF'
    assert 假库.建过 == [], '路径全都存在时不该新建任何东西'


def test_传key就直接用(假库):
    assert getpdf.resolve_collection('CTJZME6B') == 'CTJZME6B'
    assert 假库.建过 == []


def test_最后一层不存在就新建(假库):
    key = getpdf.resolve_collection('阿课题/抗冲丙烯酸酯')
    assert key.startswith('NEW')
    assert 假库.建过 == [('抗冲丙烯酸酯', 'BJVQSCA8')], '要建在阿课题下面，不是顶层'


def test_中间层不存在要报清楚而不是乱建(假库):
    """**这条是本文件的重点。** 报错要能让调用方自己改对。"""
    with pytest.raises(ValueError) as e:
        getpdf.resolve_collection('阿课题/根本没有这一层/某某')
    msg = str(e.value)
    assert '根本没有这一层' in msg, '要指出是哪一段不存在'
    assert '抗冲击' in msg and '剪切硬化材料' in msg, \
        '要把那一层实际有什么列出来 —— 否则调用方只能猜，猜不到就会编'
    assert 假库.建过 == [], '中间层缺失时一个合集都不许建'


def test_同名合集在不同父级下不会认错(假库):
    """「建库用」可以既在 A 下又在 B 下 —— 解析必须按父级区分。"""
    假库._cols.append(_col('DUP1', '建库用', 'BJVQSCA8'))
    假库._cols.append(_col('DUP2', '建库用', 'XA5PD2GU'))
    assert getpdf.resolve_collection('阿课题/建库用') == 'DUP1'
    assert getpdf.resolve_collection('专利/建库用') == 'DUP2'


def test_空输入返回None(假库):
    """空 = 没指定 = 走默认那棵树，不是错误。"""
    assert getpdf.resolve_collection('') is None
    assert getpdf.resolve_collection(None) is None
    assert getpdf.resolve_collection('   /  ') is None
