# -*- coding: utf-8 -*-
"""审稿：拆栏、拆句、假模型逐句判、回炉提示、塞错校准（2026-09-19）。

模型换成假替身：看到「待审句子」里有「编造」两个字就标 unsupported，有「错数」标 distorted，其余 ok。
测的是编排：材料给对了栏、被标的句子回到对的栏、整篇复核能把切片漏判洗白。
"""
import re

from tools.deepread import review as RV
from tools.deepread import sectioned
from tools.deepread.tests.test_sectioned import MD, FIGS, META

CONTENT = """# 【Macro】PBS 弹性体：12.5 MPa

## 导读

近期，A. Zhang 等人报道了一种聚硼硅氧烷弹性体，拉伸强度达 12.5 MPa。

## 引言

冲击防护需要速率依赖的材料，前人只做到 3.2 MPa。

## 实验

（1）主要实验药品是：PDMS（Mw 5 kDa）和硼酸。🌿（2）实验步骤是：180 °C 加热 2 h。🌿（3）测试表征方法包括：拉伸。

Question：各组分的作用是？🍁第一，PDMS 提供柔性骨架。🍁第二，硼酸提供动态 B–O 键。

## 讨论

【图1】

图1，标题为"力学性能"。图1a展示应力应变曲线；图1b比较模量。

▲图1，大图标题为"力学性能"。模量为 4.1 MPa，强度 12.5 MPa。这里有一句编造的机理解释。

【图2】

▲图2，大图标题为"流变"。交叉点出现在 15 rad/s。这里有一处错数 30 rad/s。

Question：本论文中所制备的材料为何性能优异？☘️第一，B–O 键动态交换耗散能量。

## 总结

总之，这项工作把冲击防护问题转化成了动态键设计问题。

## 通俗理解

通俗理解：像一团编造的橡皮泥，慢慢拉会流动，快拉就变硬。

## 文献信息

DOI：https://doi.org/10.1021/x
"""


def fake_json(calls, whole_ok=False):
    def chat_json(system, user, **kw):
        calls.append({'system': system[:40], 'user': user, 'kw': kw})
        if '待审句子' in user:
            body = user.split('【待审句子】', 1)[1]
            verdicts = []
            for m in re.finditer(r'^(\d+)\. (.+)$', body, re.M):
                i, c = int(m.group(1)), m.group(2)
                v = 'unsupported' if '编造' in c else 'distorted' if '错数' in c else 'ok'
                material = user.split('【待审句子】', 1)[0].replace('【原文材料】', '').strip()
                if whole_ok and not material.startswith('【'):      # 整篇原文没有【材料】分块 = 复核那一步
                    v = 'ok'
                verdicts.append({'i': i, 'v': v, 'why': '假' if v != 'ok' else ''})
            return {'verdicts': verdicts}
        if '全部图注' in user:
            return {'points': [{'k': 'result', 'text': 'tensile strength 12.5 MPa'},
                               {'k': 'result', 'text': 'crossover at 15 rad/s'},
                               {'k': 'claim', 'text': 'shear stiffening via B–O exchange'},
                               {'k': 'result', 'text': 'elongation 850%'}]}
        if '要点清单' in user:
            return {'cover': [{'i': 1, 'v': 'covered', 'where': '拉伸强度达'},
                              {'i': 2, 'v': 'covered', 'where': '交叉点'},
                              {'i': 3, 'v': 'partial', 'where': 'B–O 键'},
                              {'i': 4, 'v': 'missed', 'where': ''}]}
        return {}
    return chat_json


def test_拆栏_key_对上缓存那套_通俗理解与文献信息不审():
    keys = [k for k, _, _ in RV.sections_of(CONTENT)]
    assert keys == ['lead', 'exp', 'fig:1', 'fig:2', 'wrap']
    text = dict((k, t) for k, _, t in RV.sections_of(CONTENT))
    assert 'Question：本论文' in text['wrap'] and '总之' in text['wrap']
    assert '橡皮泥' not in ''.join(text.values())


def test_拆句_剥前缀_丢问句与短句():
    cs = RV.split_claims('Question：各组分的作用是？🍁第一，PDMS 提供柔性骨架结构。🍁第二，硼酸。短。')
    assert cs == ['PDMS 提供柔性骨架结构。']


def test_范文没有标题时整个算一栏():
    secs = RV.sections_of('近期，某某报道了一种材料。\n\n它的强度是 10 MPa。')
    assert [k for k, _, _ in secs] == ['all']


def test_html_还原成同形_markdown():
    from tools.deepread.main_text import render_html
    back = RV.html_to_content(render_html(CONTENT))
    assert [k for k, _, _ in RV.sections_of(back)] == ['lead', 'exp', 'fig:1', 'fig:2', 'wrap']
    assert '模量为 4.1 MPa' in back


def test_逐句判_被标的句子落在对的栏_要点覆盖统计():
    calls = []
    rep = RV.review(CONTENT, MD, '', fake_json(calls), META, log=lambda *a: None)
    assert rep['sections']['fig:1']['flags'][0]['v'] == 'unsupported'
    assert rep['sections']['fig:2']['flags'][0]['v'] == 'distorted'
    assert rep['n_flagged'] == 2 and rep['n_missed'] == 1 and rep['n_partial'] == 1
    assert not rep['passed']                       # 2 / 十几句 > 8%
    # 图 1 那栏的材料是图 1 的图注 + 讨论段，不是整篇
    fig1 = next(c for c in calls if '3. ' in c['user'] and '图1' in c['user'])
    assert 'Figure 1. Mechanical' in fig1['user'] and 'Figure 2. Rheological' not in fig1['user']
    assert all(c['kw'].get('purpose') == 'REVIEW' for c in calls)


def test_整篇复核能洗白切片漏判():
    calls = []
    rep = RV.review(CONTENT, MD, '', fake_json(calls, whole_ok=True), META, log=lambda *a: None, with_cover=False)
    # 假模型：材料一长（整篇）就全判 ok → 两处被标的都算切片漏了
    assert rep['n_flagged'] == 0 and rep['n_slice_miss'] == 2 and rep['passed']


def test_回炉提示只给有问题的栏_漏要点挂收尾栏():
    calls = []
    rep = RV.review(CONTENT, MD, '', fake_json(calls), META, log=lambda *a: None)
    notes = RV.notes_for(rep)
    assert set(notes) == {'fig:1', 'fig:2'}         # 漏 1 条没超过 MISS_TOL，不打回收尾栏
    assert '编造' in notes['fig:1'] and '错数' in notes['fig:2']
    rep['cover'] += [{'k': 'result', 'text': 'x', 'v': 'missed', 'where': ''}] * 2
    assert 'wrap' in RV.notes_for(rep)


def test_compose_带_notes_只重跑那几栏_且按标记号找图号(tmp_path):
    from tools.deepread.tests.test_sectioned import fake_chat
    calls = []
    cache = str(tmp_path / 'parts.json')
    content, _ = sectioned.compose(MD, '', FIGS, META, fake_chat(calls), log=lambda *a: None, cache=cache)
    n0 = len(calls)
    calls.clear()
    marks = [int(m) for m in re.findall(r'【图(\d+)】', content)]
    content2, _ = sectioned.compose(MD, '', FIGS, META, fake_chat(calls), log=lambda *a: None, cache=cache,
                                    notes={'fig:%d' % marks[0]: '\n\n⚠ 审稿指出……'})
    assert 0 < len(calls) < n0
    assert any('审稿指出' in c['user'] for c in calls)


def test_塞错_能塞进去_也能被认出来():
    bad, injected = RV.corrupt(CONTENT, seed=2)
    assert bad != CONTENT and len(injected) >= 5
    assert any('W m' in s or '112°' in s or '150 °C' in s for s in injected)
    rep = {'sections': {'x': {'flags': [{'claim': s} for s in injected[:3]]}}}
    assert RV._hit(rep, injected) == 3


def test_to_markdown_不炸():
    calls = []
    rep = RV.review(CONTENT, MD, '', fake_json(calls), META, log=lambda *a: None)
    md = RV.to_markdown(rep, 'KEY')
    assert '不过' in md and 'unsupported' in md


def test_材料超窗口时按句子挑段落而不是盲截():
    filler = '\n\n'.join('Background paragraph number %d about nothing in particular.' % i for i in range(400))
    target = 'The PBS-12 sample showed a modulus of 4.1 MPa at 180 °C.'
    material = filler + '\n\n' + target            # 目标段在最后，盲截前 N 字符一定丢
    out = RV._cap(material, ['PBS-12 样品在 180 °C 下模量为 4.1 MPa。'], cap=3000)
    assert target in out and len(out) <= 3000
    assert RV._cap('short', ['x'], cap=3000) == 'short'
