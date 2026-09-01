# -*- coding: utf-8 -*-
"""精读评测集的离线测试 —— 不碰真实评测集，全在临时目录里。

原来是 `shared/adapters/evalset/selftest.py` 的 6 项；R5 窗随代码搬进工具，
顺便改成 pytest（原来那份要手动跑，等于没人跑）。
另加两条这块最该守的：评分器不许被内嵌图骗到、废品线只有一个出处。
"""
import json
import os
import tomllib

import pytest

from shared.kernel import paths
from tools.deepread import evals, main_text
from tools.deepread.evals.scorers import quality


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """评测集与文献库都指到临时目录 —— 测试污染用户数据是不可接受的。"""
    monkeypatch.setattr(evals, 'EVALSET', str(tmp_path / 'evalset.json'))
    monkeypatch.setattr(paths, 'CURATED', str(tmp_path / 'curated'))
    return tmp_path


def test_空评测集不炸(sandbox):
    assert evals.load() == {}
    assert evals.get('X') is None


def test_评价存取往返(sandbox):
    evals.save('AAAA1111', 'good', title='测试文献一')
    r = evals.get('AAAA1111')
    assert r['verdict'] == 'good' and r['title'] == '测试文献一'


def test_非法评分被拒(sandbox):
    """不能悄悄存进一个无意义的值 —— 存进去了才发现，那批数据就废了。"""
    with pytest.raises(ValueError):
        evals.save('BBBB2222', 'maybe')
    assert evals.get('BBBB2222') is None


def test_pending只列没评过的(sandbox):
    evals.save('AAAA1111', 'good')
    evals.save('CCCC3333', 'bad', reasons=['too_vague'])
    assert evals.pending(['AAAA1111', 'CCCC3333', 'DDDD9999']) == ['DDDD9999']


def test_统计与样本够不够(sandbox):
    """没有快照的评价不计入客观指标对比 —— 否则会拿 None 去算平均。"""
    evals.save('AAAA1111', 'good')
    evals.save('CCCC3333', 'bad')
    s = evals.stats()
    assert s['total'] == 2 and s['good'] == 0 and s['bad'] == 0
    assert not s['ready']
    # 还差几篇由 stats 算，不由调用方硬编码
    assert s['need_good'] == evals.MIN_GOOD and s['need_bad'] == evals.MIN_BAD


def test_快照能算且不存在的返回None(sandbox):
    p = paths.summary('AAAA1111')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        f.write('<h2>导读</h2><p>拉伸强度 12 MPa，断裂伸长率 800 %。</p>'
                '<h2>总结</h2><img src="x">')
    snap = evals.snapshot('AAAA1111')
    assert snap['chars'] > 0 and snap['figures'] == 1
    assert snap['sections'] == 2
    # 2 处：`12 MPa` 与 `800 %`。
    # **这里曾经断言的是 1** —— 正则以词边界收尾，而 `%` 后面跟的是中文标点，
    # 于是百分数从来没被数进去过。R5 是搬家窗不改逻辑，就先把错的现状钉在这里，
    # 并写明「将来修好了这条会红，那时记得指标口径变了、历史快照不可比」。
    # 2026-09-01 真的修了（METRICS_VER 1 → 2），这条也真的红了 —— 安全网起作用了。
    # 配套动作：快照带上 metrics_ver、stats() 点名旧口径的、recompute() 刷齐。
    assert snap['numbers'] == 2
    assert 'size_kb' in snap and 'mtime' in snap
    assert evals.snapshot('EEEE0000') is None          # 合法 key，但没这份文件
    assert evals.snapshot('不是key') is None            # 怪 key 也只是 None，不许炸


def test_评价里存的是当时的快照(sandbox):
    """评分和快照必须同时落盘 —— 只有分数没有快照，将来没法做校准。"""
    p = paths.summary('AAAA1111')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, 'w', encoding='utf-8').write('<p>拉伸强度 12 MPa</p>')
    evals.save('AAAA1111', 'good')
    assert evals.get('AAAA1111')['snapshot']['numbers'] == 1
    assert json.load(open(evals.EVALSET, encoding='utf-8'))['AAAA1111']['snapshot']


def test_内嵌图不许污染数值密度():
    """曾把 6641 字的精读算出 13471 处数值 —— base64 图里全是数字字母。

    **一个错得离谱的指标比没有指标更糟**：它不会报错，只会安静地污染将来的校准。
    """
    fake_b64 = 'iVBORw0KGgo' + '9' * 500 + 'nm' * 200
    html = f'<p>拉伸强度 12 MPa</p><img src="data:image/png;base64,{fake_b64}">'
    m = quality.metrics(html)
    assert m['numbers'] == 1, f'内嵌图被算进数值了：{m}'
    assert m['figures'] == 1


def test_废品线只有一个出处():
    """`thresholds.toml` 的 min_chars 与 main_text.MIN_OK 必须相等。

    两处各写一个数字，早晚会改一处忘一处 —— 那时「什么算废品」就有了两个答案。
    """
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'evals', 'thresholds.toml')
    with open(p, 'rb') as f:
        t = tomllib.load(f)
    assert t['quality']['min_chars'] == main_text.MIN_OK


# ────────────────────────── 指标口径（v2，2026-09-01）──────────────────────────

def test_百分数要被数进去():
    """v1 的正则以 `\b` 收尾，而 `%` 后面通常是中文标点 —— 于是整整一类数值
    从来没被数进去过。百分数在材料文献里恰恰最常见（伸长率、修复效率、保持率）。
    """
    from tools.deepread.evals.scorers import quality
    html = ('<p>拉伸强度 12 MPa，断裂伸长率 800 %，修复效率 95%，'
            '模量 1.2 GPa，5 wt% 硼，120 °C 下 30 min</p>')
    hits = quality._NUM_RE.findall(html)
    assert quality.metrics(html)['numbers'] == 7, f'只数出 {hits}'
    for want in ('800 %', '95%', '5 wt%', '120 °C'):
        assert want in hits, f'漏了 {want}（{hits}）'


def test_字母单位仍然要求词边界():
    """放开 `%` 的边界之后，别把字母单位的边界也一起放开了。"""
    from tools.deepread.evals.scorers import quality
    assert quality._NUM_RE.findall('<p>5 minutes</p>') == [], '「5 minutes」不该算成 5 min'
    assert quality._NUM_RE.findall('<p>反应 30 min。</p>') == ['30 min']


def test_快照带着口径版本号(sandbox):
    """没有版本号就没法知道两条快照是不是同一把尺子量的 —— 而这种不可比不会报错。"""
    from tools.deepread.evals.scorers import quality
    assert quality.metrics('<p>1 MPa</p>')['metrics_ver'] == quality.METRICS_VER


def test_旧口径的快照会被点名(sandbox):
    """`stats()` 要把旧口径的快照报出来，但**绝不擅自丢掉**用户的评价。"""
    from tools.deepread import evals
    evals.save('ABCD1234', 'good', title='假的')
    data = evals.load()
    data['ABCD1234']['snapshot'] = {'chars': 1, 'figures': 0, 'numbers': 0,
                                    'sections': 0, 'metrics_ver': 1}
    evals._write(data)

    st = evals.stats()
    assert st['stale'] == ['ABCD1234'], '旧口径的快照没被点名'
    assert st['total'] == 1, '点名不等于丢掉 —— 评价必须还在'
