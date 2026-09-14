# -*- coding: utf-8 -*-
"""分段精读：材料按类切、每栏一次调用、骨架由脚本拼、【图N】齐全、数字回查（2026-09-14）。

模型换成假替身：它只看系统提示词是哪一栏，吐出合形的中文。测的是编排与拼装。
"""
import re

from tools.deepread import sectioned

MD = """# Shear-Stiffening Polyborosiloxane Elastomers

## Abstract

We report a polyborosiloxane (PBS) elastomer with tensile strength 12.5 MPa and 850% elongation.

## 1. Introduction

Impact protection needs rate-dependent materials. Prior work reached only 3.2 MPa.

## 2. Experimental

### 2.1 Materials

PDMS (Mw 5 kDa, Gelest) and boric acid (99%, Aldrich) were used.

### 2.2 Synthesis

PDMS and boric acid were heated at 180 °C for 2 h under N2.

## 3. Results and Discussion

The stress–strain curves (Figure 1) show a modulus of 4.1 MPa. Figure 1b compares three ratios.

![](images/a.jpg)

Figure 1. Mechanical properties of PBS elastomers. (a) Stress–strain curves; (b) modulus versus B/Si ratio.

Rheology (Fig. 2) reveals a crossover at 15 rad/s.

![](images/b.jpg)

Figure 2. Rheological behavior. (a) Storage modulus; (b) tan delta.

## 4. Conclusions

A PBS elastomer with 12.5 MPa strength was obtained.

## References

1. Yang et al. 797.4 MPa. 2020.
"""

FIGS = [{'b64': 'x', 'caption': 'Figure 1. Mechanical', 'num': 1},
        {'b64': 'y', 'caption': 'Figure 2. Rheological', 'num': 2},
        {'b64': 'z', 'caption': '', 'num': 3}]          # 目录图：没图注，不写字
META = {'title': 'Shear-Stiffening Polyborosiloxane Elastomers', 'authors': 'A. Zhang, B. Li',
        'journal': 'Macromolecules', 'year': '2026', 'doi': '10.1021/acs.macromol.6c00001'}


def fake_chat(calls):
    def chat(system, user, purpose=None, model=None, temperature=0.3, max_tokens=None, thinking=None):
        calls.append({'system': system, 'user': user, 'max_tokens': max_tokens})
        if '【导读】' in system:
            return '【导读】\n近期，A. Zhang, B. Li 报道了拉伸强度 12.5 MPa 的 PBS 弹性体🎉。\n【引言】\n冲击防护需要率相关材料。\n\n此前只有 3.2 MPa。'
        if '【实验】' in system:
            return ('【实验】\n（1）主要实验药品是：PDMS（Mw 5 kDa，Gelest）、硼酸（99%，Aldrich）。\n\n'
                    '（2）实验步骤是：🌿180 °C 下加热 2 h；🌿氮气保护。\n\n（3）测试表征方法包括：拉伸、流变。\n'
                    '【Q1】\nQuestion：各组分的作用是？🍁PDMS：柔性主链；🍁硼酸：动态 B–O 交联。')
        if '只讲一张图' in system:
            n = re.search(r'这是图 (\d+)', user).group(1)
            return f'图{n}，标题为"力学性能"。图{n}a展示应力应变；图{n}b比较模量。\n\n▲图{n}，大图标题为"力学性能"。模量 4.1 MPa，交叉点 15 rad/s，还有一个编的 77.7 MPa。'
        if '【Q2】' in system:
            return ('【Q2】\nQuestion：本论文中所制备的材料为何性能优异？☘️第一，动态 B–O 键；☘️第二，链缠结。\n'
                    '【总之】\n总之，这项工作把冲击防护问题转化成了动态键设计问题。\n'
                    '【通俗理解】\n通俗理解：像一团遇急变硬的橡皮泥。\n'
                    '【标题】\n【Macromolecules】遇急变硬的硅硼弹性体：强度 12.5 MPa')
        return ''
    return chat


def test_骨架齐全_图由脚本放_数字回查():
    calls = []
    content, st = sectioned.compose(MD, '', FIGS, META, fake_chat(calls), log=lambda *a: None)
    for h in ('# 【Macromolecules】', '## 导读', '## 引言', '## 实验', '（1）', '（2）', '（3）',
              'Question：各组分的作用是？', '## 讨论', '【图1】', '【图2】', '▲图1', '▲图2',
              'Question：本论文中所制备的材料为何性能优异？', '## 总结', '## 通俗理解',
              '## 文献信息', 'https://doi.org/10.1021/acs.macromol.6c00001'):
        assert h in content, h
    # 顺序：图 1 的两段在【图1】之后、【图2】之前
    assert content.index('【图1】') < content.index('▲图1') < content.index('【图2】') < content.index('▲图2')
    assert st['figs_two_para'] == 2 and st['has_plain'] and not st['review']
    assert '【图3】' not in content and st['n_numbered'] == 2      # 没图注的不写字，留给补充图
    # 编的 77.7 被抓出来；原文有的 12.5 / 4.1 / 15 不报
    assert '77.7' in st['unverified'] and '12.5' not in st['unverified'] and '4.1' not in st['unverified']
    # 调用次数 = 导读 + 实验 + 每图一次 + 收尾
    assert len(calls) == 2 + 2 + 1


def test_每栏只喂它该看的材料():
    calls = []
    sectioned.compose(MD, 'SI text: 5 kDa PDMS 0.5 g, 180 °C', FIGS, META, fake_chat(calls), log=lambda *a: None)
    lead, exp, f1, f2, wrap = calls
    assert 'Introduction' not in exp['user'] and 'Materials' not in lead['user'].split('【结论】')[1]
    assert 'boric acid' in exp['user'] and 'SI text' in exp['user']          # 实验栏拿到方法节 + SI
    assert 'Figure 1.' in f1['user'] and 'Figure 2.' not in f1['user'].split('【正文里讨论它的段落】')[0]
    assert 'crossover at 15 rad/s' in f2['user'] and '797.4' not in f2['user']  # 参考文献不进材料
    assert '▲图1' in wrap['user'] and '▲图2' in wrap['user']                  # 收尾看的是已写好的深解


def test_综述按综述写():
    calls = []
    meta = dict(META, title='Recent advances in polyborosiloxane elastomers: a review')
    sectioned.compose(MD, '', FIGS, meta, fake_chat(calls), log=lambda *a: None)
    assert '系统总结了' in calls[0]['system']
    assert '主要材料体系' in calls[1]['system'] and '综述' in calls[-1]['system']


def test_数字回查的过滤():
    src = 'strength 12.5 MPa, 1 000 cycles, 2020 paper, Figure 3'
    bad = sectioned.unverified_numbers('图3 显示 12.5 MPa，1000 次循环，2020 年，第 5 组，3 种方法，缺 88.8 MPa', src)
    assert bad == ['88.8']
