# -*- coding: utf-8 -*-
"""ask 的可追溯性评测 —— **不调模型、不碰向量库、秒级**。

验的是这个工具的全部卖点：答案带得出出处。
不验答案质量（那要「已知答案在哪一篇」的问题 + 真调模型，见 `evals/README.md`）。

做法：把向量库和模型调用都换成假的，只看**结构**——
喂进去 N 段材料，就该有 N 段带出处进上下文，来源列表不多不少。
"""
import pytest

from tools import ask
from tools.ask import evals
from tools.ask.evals.scorers import traceability as sc


class _FakeStore:
    """假向量库：query() 返回预先摆好的片段。"""

    def __init__(self, hits):
        self._hits = hits

    def query(self, _vec, n=5):
        return self._hits[:n]


@pytest.fixture
def wired(monkeypatch):
    """把外部依赖全换成假的，并把送进模型的上下文截下来。"""
    box = {}

    def fake_answer_with(system, user):
        box['system'] = system
        box['user'] = user
        return '（假答案）'

    monkeypatch.setattr(ask, 'embed', lambda t: [0.0])
    monkeypatch.setattr(ask, 'answer_with', fake_answer_with)

    def use(hits):
        monkeypatch.setattr(ask, '_store', lambda: _FakeStore(hits))
        return ask.ask_answer('随便问点什么')

    return use, box


def _hit(title, doi, doc):
    return {'doc': doc, 'meta': {'title': title, 'doi': doi}}


def test_每段材料都带着出处进上下文(wired):
    """模型只能引用它看得见出处的东西。少一个标记，那一段就成了「无主的话」——
    模型据此作答时，用户拿不到出处，而**这个工具的全部价值就是出处**。
    """
    use, box = wired
    r = use([_hit('第一篇论文的标题', '10.1/a', '正文片段一'),
             _hit('第二篇论文的标题', '10.1/b', '正文片段二'),
             _hit('第三篇论文的标题', '10.1/c', '正文片段三')])
    ok, why = sc.check_context(box['user'], 3)
    assert ok, why
    assert r['chunks'] == 3


def test_来源列表不多不少(wired):
    """多了 = 用户会去翻一篇根本没参与作答的文献；少了 = 他不知道这句话哪来的。"""
    use, _box = wired
    titles = ['第一篇论文的标题', '第二篇论文的标题']
    r = use([_hit(titles[0], '10.1/a', 'x'), _hit(titles[1], '10.1/b', 'y')])
    ok, why = sc.check_sources(r['sources'], titles)
    assert ok, why


def test_同一篇的多个片段只算一条来源(wired):
    """一篇文献被切成好几块是常态。来源列表里重复列同一篇，
    会让用户以为「有好几篇都支持这个说法」——**那是凭空放大了证据强度**。
    """
    use, _box = wired
    r = use([_hit('同一篇论文', '10.1/a', '第一块'),
             _hit('同一篇论文', '10.1/a', '第二块'),
             _hit('同一篇论文', '10.1/a', '第三块')])
    assert len(r['sources']) == 1, f'同一篇被列了 {len(r["sources"])} 次'
    assert r['chunks'] == 3, '片段数不该跟着去重 —— 那是两件事'


def test_向量库空的时候不硬答(wired):
    """没有材料就不该调模型。硬答出来的东西**没有任何出处**，
    而用户看到的仍然是一段像模像样的中文 —— 那比报错危险得多。
    """
    use, box = wired
    r = use([])
    assert r == {'answer': '', 'sources': [], 'chunks': 0}
    assert 'user' not in box, '没有材料却还是调了模型（花钱 + 无出处的答案）'


def test_阈值只有一个出处():
    """跟别的工具一样：数字写在 thresholds.toml，不在 .py 里再抄一遍。"""
    assert 0 < evals.MIN_PASS_RATE <= 1.0
