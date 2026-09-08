# -*- coding: utf-8 -*-
"""章节分类的守卫 —— **每一条都是全库 43 篇实测踩出来的**（2026-09-08）。

不是想出来的用例。想出来的用例只会覆盖你已经想到的情况。
"""
import pytest

from shared.domain.schema import outline as O


@pytest.mark.parametrize('title, kind', [
    # ⚠ 这一条最值钱：原来剥编号前缀时把 INTRODUCTION 开头的 I 当罗马数字剥掉，
    # 变成 NTRODUCTION —— **43 篇里每一篇的引言都成了未分类**，
    # 而汇总统计只会显示「未分类偏高」，完全看不出是这个原因。
    ('INTRODUCTION', O.BACKGROUND),
    ('I. Introduction', O.BACKGROUND),
    ('1. Introduction', O.BACKGROUND),
    # Nature/Science 风格：描述性小标题，全篇没有 Results 字样
    ('Anti-impact ability and safeguarding of PDBS', O.RESULTS),
    ('Thermal stiffening behavior of PDU-PDBA', O.RESULTS),
    ('Autonomous Self-Healing Property', O.RESULTS),
    ('The effect of the B/Si atomic ratio', O.RESULTS),
    ('Oxidation stability of borosiloxane gels', O.RESULTS),
    # MineRU 把投稿信息和作者块识别成标题
    ('Received 8 June 2023; accepted 17 August 2023;', O.NONBODY),
    ('Authors', O.NONBODY),
    ('References', O.NONBODY),
    # 国产期刊英文稿里的中文题名
    ('基于联硼结构的新型剪切增稠超分子材料', O.ABSTRACT),
    # 常规的那些别改坏了
    ('2.1. Materials', O.SYNTHESIS),
    ('2.6. Mechanical property test', O.METHODS),
    ('RESULTS AND DISCUSSION', O.RESULTS),
    ('4. Conclusion', O.CONCLUSION),
    ('Abstract', O.ABSTRACT),
])
def test_真实标题归对类(title, kind):
    assert O.classify(title) == kind


def test_认不出就说认不出_不猜():
    """空类别是事实，猜一个是错 —— 跟项目里「宁可空着也不要假数据」同一条规矩。"""
    assert O.classify('Zzz qqq wwww') == O.UNKNOWN


def test_子节判不出时继承父节():
    assert O.classify('2.4. General procedure', parent_kind=O.SYNTHESIS) == O.SYNTHESIS


def test_大块的非正文不会被菜单藏起来():
    """MineRU 会把投稿信息当标题，后面挂着上万字真正文（实测一篇 13462 字）。

    一刀切隐藏「非正文」会把那些正文一起弄丢。
    """
    o = {'sections': [
        {'id': 's1', 'kind': O.NONBODY, 'title': 'References', 'chars': 900,
         'n_numbers': 40, 'n_tables': 0, 'n_figures': 0},
        {'id': 's2', 'kind': O.NONBODY, 'title': 'Received 1 Jan; accepted 2 Feb',
         'chars': 13462, 'n_numbers': 60, 'n_tables': 1, 'n_figures': 3}]}
    m = O.menu(o)
    assert 's1' not in m, '小块参考文献该藏起来'
    assert 's2' in m, '上万字的块不许藏 —— 里面多半是真正文'


class Test判据太弱的关键词:
    """`analysis` 这个词太弱，谁都能沾（2026-09-08 真跑一篇 Wiley 论文时发现）。

    `2.3.3 | Thermogravimetric Analysis (TGA)` 是方法节，
    `3.7 | DSC Analysis` 在结果章下面 —— 两个都被这个词拽成了「讨论」。
    **判据太弱的关键词不如不写**，让它落到父节继承那一档，反而全对。
    """

    def test_TGA是方法不是讨论(self):
        assert O.classify('2.3.3 | Thermogravimetric Analysis (TGA)',
                          parent_kind=O.METHODS) == O.METHODS

    def test_结果章下的DSC分析算结果(self):
        assert O.classify('3.7 | DSC Analysis', parent_kind=O.RESULTS) == O.RESULTS

    def test_真正的机理节还是讨论(self):
        assert O.classify('3.6.1 | Mechanism', parent_kind=O.RESULTS) == O.DISCUSSION
        assert O.classify('Discussion') == O.DISCUSSION
