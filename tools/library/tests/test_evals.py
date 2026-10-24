# -*- coding: utf-8 -*-
"""library 的金标评测 —— **需要真实证据库数据，默认不跑**。

    python -m pytest tools/library -m live      # 在主力机（有证据库数据）上跑

验的是对任何库都成立的**不变量**（见 `evals/__init__.py`），不写死条目。
2026-10-13 Zotero 移出平台：原来搜的是 Zotero，现在搜证据库（`dbsearch.find`）。
"""
import pytest

from shared.kernel import catalog
from tools.library import dbsearch, evals

pytestmark = pytest.mark.live


@pytest.fixture(scope='module')
def sample():
    """从证据库里取几篇带标题的当样本。库是空的就跳过（不是失败：空库没什么可验的）。"""
    rows = [r for r in catalog.scan() if (r.get('title') or '').strip()]
    if not rows:
        pytest.skip('证据库里没有带标题的文献，无从验起')
    return rows[:evals.SAMPLE_N]


def test_用一篇自己的标题能搜到它自己(sample):
    """最基本的检索不变量。它挂了意味着：分词坏了 / 归一坏了 / 编码坏了。"""
    hit, missed = 0, []
    for it in sample:
        title = ' '.join(it['title'].split())
        probe = ' '.join(title.split()[:6])          # 长标题只取前几个词，够定位了
        ids = [r['id'] for r in dbsearch.find(q=probe, limit=50)[0]]
        if it['id'] in ids:
            hit += 1
        else:
            missed.append(f'{it["id"]}「{title[:40]}」')
    rate = hit / len(sample)
    assert rate >= evals.MIN_PASS_RATE, (
        f'{hit}/{len(sample)} 篇能用自己的标题搜到自己，低于阈值 '
        f'{evals.MIN_PASS_RATE}：\n  ' + '\n  '.join(missed))


def test_搜乱码要返回空而不是返回全部():
    """**「返回全部」比「返回 0 条」危险得多** —— 它看起来像在工作。"""
    assert dbsearch.find(q='zzqqxx不存在的词zzqqxx', limit=10)[0] == []


def test_limit说几条就最多几条(sample):
    assert len(dbsearch.find(q='a', limit=3)[0]) <= 3


def test_每条都带id和title(sample):
    """下游（文献库应用、Claude Science）全靠这两个字段定位一篇文献，缺一个就断链。"""
    bad = [r for r in dbsearch.find(q='a', limit=10)[0] if not r.get('id') or 'title' not in r]
    assert not bad, f'缺字段：{bad[:3]}'
