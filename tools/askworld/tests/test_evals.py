# -*- coding: utf-8 -*-
"""askworld 的可追溯性评测 —— **不调模型、不联网、秒级**。

`evals/README.md` 原话：「同 ask，但更关键 —— **本工具的全部价值就是可追溯**」。
问自己的库，答错了用户还能凭印象察觉；问全世界，他对这些文献一无所知，
**唯一能核对的就是出处**。

不验答案质量（要真调 Sciverse + 大模型，且标准答案得用户来判）。
"""
import pytest

from tools import askworld
from tools.askworld import evals
from tools.askworld.evals.scorers import traceability as sc


@pytest.fixture
def wired(monkeypatch):
    """把检索、翻译、模型全换成假的，并截下送进模型的上下文。"""
    box = {}

    def fake_chat(system, user, **kw):
        box['user'] = user
        return '（假答案）'

    monkeypatch.setattr(askworld, 'to_english', lambda q: 'english query')
    monkeypatch.setattr(askworld, 'chat', fake_chat)

    def use(evidence):
        monkeypatch.setattr(askworld, 'ask_evidence', lambda *a, **k: evidence)
        return askworld.ask_world('随便问点什么')

    return use, box


def _ev(title, score, year=2024, page=3, chunk='原文片段'):
    return {'title': title, 'score': score, 'year': year,
            'page': page, 'chunk': chunk, 'doi': '10.1/x'}


def test_每条证据都带着出处进上下文(wired):
    """出处要带到「第几页」——用户拿这个去核对原文。
    少一个标记，那段话就成了无主的话，而他对这些文献一无所知。
    """
    use, box = wired
    use([_ev('第一篇', 0.9), _ev('第二篇', 0.85), _ev('第三篇', 0.8)])
    ok, why = sc.check_context(box['user'], 3)
    assert ok, why
    assert '第3页' in box['user'], '页码没带进上下文 —— 用户没法核对到具体位置'


def test_相关度不够的证据要被筛掉(wired):
    """**宁可少给几条，也不要拿跑题片段污染答案。**

    跑题片段最坏的地方不是没用，是模型会**硬把它编进答案**，
    而它带着出处，看上去比没有出处更可信。
    """
    use, _box = wired
    r = use([_ev('够相关的', 0.9), _ev('跑题的', 0.01)])
    titles = [e['title'] for e in r['evidence']]
    assert '跑题的' not in titles, f'低分证据没被筛掉：{titles}'


def test_一条证据都没有时不硬答(wired):
    """没证据就返回空，让调用方去提示用户 —— 而不是编一段带假出处的话。"""
    use, box = wired
    r = use([])
    assert r['answer'] == '' and r['evidence'] == []
    assert 'user' not in box, '没有证据却还是调了模型（花钱 + 无依据的答案）'
    assert r['query_used'] == 'english query', '用了哪个检索式要如实带回去'


def test_全部被筛掉也不硬答(wired):
    """有证据但全都不够相关，等价于没证据 —— 这条最容易漏，因为「有返回」。"""
    use, box = wired
    r = use([_ev('全都跑题', 0.001), _ev('也跑题', 0.002)])
    assert r['answer'] == '' and r['evidence'] == []
    assert 'user' not in box


def test_检索式一律转英文(wired):
    """踩坑 #35：中文检索式让全球文献召回质量崩塌。

    这条不是「优化」，是这个工具能不能用的前提 —— 而它失效时**不会报错**，
    只会安静地少召回一大半。
    """
    use, _box = wired
    r = use([_ev('一篇', 0.9)])
    assert r['query_used'] == 'english query'


def test_阈值只有一个出处():
    assert 0 < evals.MIN_PASS_RATE <= 1.0
