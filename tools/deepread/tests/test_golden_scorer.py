# -*- coding: utf-8 -*-
"""对着范文打分：骨架 / 图两段 / 篇幅比 / 数字覆盖 / 术语覆盖（纯函数，2026-09-15）。"""
from tools.deepread.evals.scorers import golden as G

REF = ('# 【AFM】x\n\n来源: 高分子学人 · 2026-09-01 · a.md\nDOI: 10.1/x\n\n---\n\n'
       '近期，A B 报道了 PDMS-IU-12 弹性体，拉伸强度 5.1 MPa，自愈率 97%。\n\n![](http://x/1.jpg)\n\n'
       '（1）实验药品是：LiTFSI。（2）实验步骤是：🌿加热 2 h。（3）测试表征。\n\n'
       'Question：各组分的作用是？🍁a；🍁b；🍁c\n\n图1，标题为"x"。▲图1，大图标题为"x"。模量 4.2 MPa。\n\n'
       'Question：本论文中所制备的材料为何性能优异？☘️第一；☘️第二\n\n总之，好。\n\n通俗理解：像橡皮泥。\n')

OURS_HTML = ('<html><body><h1>【AFM】y</h1><h2 class="section">导读</h2><p>近期，A B 报道了 PDMS-IU-12，拉伸强度 5.1 MPa。</p>'
             '<h2 class="section">引言</h2><p>背景。</p><h2 class="section">实验</h2><p>（1）药品 LiTFSI</p><p>（2）步骤🌿加热 2 h</p><p>（3）表征</p>'
             '<p>Question：各组分的作用是？🍁a；🍁b</p><h2 class="section">讨论</h2><img src="data:x">'
             '<p>图1，标题为"x"。</p><p>▲图1，大图标题为"x"。模量 4.2 MPa。</p>'
             '<p>Question：本论文中所制备的材料为何性能优异？☘️第一；☘️第二；☘️第三</p>'
             '<h2 class="section">总结</h2><p>总之，好。</p><h2 class="section">文献信息</h2><p>DOI：x</p></body></html>')


def test_文本提取():
    r = G.text_of_reference(REF)
    assert r.startswith('近期') and '![' not in r and '来源' not in r
    o = G.text_of_html(OURS_HTML)
    assert '## 导读' in o and 'data:x' not in o and '\n图1，' in o


def test_打分各项():
    d = G.score(G.text_of_html(OURS_HTML), G.text_of_reference(REF))
    assert d['skeleton'] == 10 and d['fig_two_para'] == 1.0
    assert d['ref_numbers'] == 4                    # 5.1 MPa / 97% / 2 h / 4.2 MPa
    assert d['number_coverage'] == 0.75 and d['numbers_missed'] == ['97']
    assert 'PDMS-IU-12' in G._terms(G.text_of_reference(REF)) and d['term_coverage'] == 1.0
    assert d['q1_items'] == 2 and d['q2_items'] == 3 and not d['has_plain'] and d['ref_has_plain']
    assert 0 < d['composite'] <= 100


def test_综合分对缺栏目敏感():
    full = G.score(G.text_of_html(OURS_HTML), G.text_of_reference(REF))['composite']
    less = G.score(G.text_of_html(OURS_HTML.replace('<p>总之，好。</p>', '')), G.text_of_reference(REF))['composite']
    assert less < full


def test_汇总中位数():
    rows = [G.score(G.text_of_html(OURS_HTML), G.text_of_reference(REF))] * 3
    a = G.aggregate(rows)
    assert a['n'] == 3 and a['skeleton'] == 10 and a['plain_rate'] == 0.0
