# -*- coding: utf-8 -*-
"""library 的金标评测 —— **需要真实 Zotero，默认不跑**。

    python -m pytest tools/library -m live      # 在开着 Zotero 的机器上跑

为什么必须是 live：这块要回答的是「在**用户真实的库里**，搜一个词能不能把
该出来的搜出来」。拿造出来的假库测，测的是 urllib 通不通，不是检索质量。

为什么不写死条目：见 `evals/golden/README.md` —— 写死的话用户改一篇标题就红，
而那种红不代表出问题。这里验的是对任何库都成立的**不变量**。
"""
import pytest

from tools import library
from tools.library import evals

pytestmark = pytest.mark.live


@pytest.fixture(scope='module')
def sample():
    """从库里取几篇当样本。库是空的就跳过（不是失败：空库没什么可验的）。"""
    items = library.recent(days=3650, limit=evals.SAMPLE_N * 3)
    items = [i for i in items if (i.get('title') or '').strip()]
    if not items:
        pytest.skip('Zotero 库里没有带标题的条目，无从验起')
    return items[:evals.SAMPLE_N]


def test_用一篇自己的标题能搜到它自己(sample):
    """最基本的检索不变量。它挂了意味着：分词坏了 / qmode 传错 / 编码坏了。

    阈值允许挂一篇：标题带下标、希腊字母、书名号的条目，Zotero 的
    `titleCreatorYear` 分词偶尔搜不回自己 —— 那是它的行为，不是我们的 bug。
    """
    hit, missed = 0, []
    for it in sample:
        title = it['title'].strip()
        probe = ' '.join(title.split()[:6])          # 长标题只取前几个词，够定位了
        keys = [r['key'] for r in library.search(probe, limit=50)]
        if it['key'] in keys:
            hit += 1
        else:
            missed.append(f'{it["key"]}「{title[:40]}」')
    rate = hit / len(sample)
    assert rate >= evals.MIN_PASS_RATE, (
        f'{hit}/{len(sample)} 篇能用自己的标题搜到自己，低于阈值 '
        f'{evals.MIN_PASS_RATE}：\n  ' + '\n  '.join(missed))


def test_搜乱码要返回空而不是返回全部():
    """**「返回全部」比「返回 0 条」危险得多** —— 它看起来像在工作。

    检索退化成「忽略查询词」时，用户会拿到一堆不相干的文献，
    而且不会怀疑，因为确实「搜到东西了」。
    """
    assert library.search('zzqqxx不存在的词zzqqxx', limit=10) == []


def test_limit说几条就最多几条(sample):
    """分页参数写反的话，一次全库拉取会把 Zotero 打到限流（踩坑 #10）。"""
    assert len(library.search('a', limit=3)) <= 3


def test_每条都带key和title(sample):
    """下游（精读、抽取、问答）全靠这两个字段定位一篇文献，缺一个就断链。"""
    bad = [r for r in library.search('a', limit=10)
           if not r.get('key') or 'title' not in r]
    assert not bad, f'压平后缺字段：{bad[:3]}'
