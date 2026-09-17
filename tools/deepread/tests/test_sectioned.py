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
    def chat(system, user, purpose=None, model=None, temperature=0.3, max_tokens=None,
             thinking=None, provider=None):
        calls.append({'system': system, 'user': user, 'max_tokens': max_tokens})
        if '【导读】' in system:
            return ('【导读】\n近期，A. Zhang, B. Li 报道了拉伸强度 12.5 MPa 的 PBS 弹性体🎉。\n'
                    '【引言】\n冲击防护需要率相关材料。\n\n此前只有 3.2 MPa。')
        if '【实验】' in system:
            # 故意犯错：用错的🌿、英文冒号、改写过的问句 —— 都该被脚本修回来
            # 第一稿漏掉清单里的 0.5 g / 4.1 MPa；被脚本点名后第二稿补上 —— 清单先行的闭环（2026-09-17）
            extra = '，投料 0.5 g，模量 4.1 MPa' if '漏了' in user else ''
            return ('【实验】\n(1）主要实验药品是：PDMS（Mw 5 kDa，Gelest）、硼酸（99%，Aldrich）。\n\n'
                    '（2）实验步骤是：🌿180 °C 下加热 2 h' + extra + '；🍁氮气保护。\n\n（3）测试表征方法包括：拉伸、流变。\n'
                    '【Q1】\nQuestion: 各个组分的作用是？🍁PDMS：柔性主链；🌿硼酸：动态 B-O 交联。')
        if '只讲一张图' in system:
            n = re.search(r'这是图 (\d+)', user).group(1)
            # 第一稿编一个 77.7；被脚本指出「原文没有」后第二稿改掉 —— 数字回查的闭环
            fake = '' if '找不到' in user else '，还有一个编的 77.7 MPa'
            return (f'图 {n}，标题为"力学性能"。图{n}a展示应力应变；图{n}b比较模量。\n\n'
                    f'▲ 图{n}，大图标题为"力学性能"。模量 4.1 MPa，交叉点 15 rad/s{fake}。')
        if '【Q2】' in system:
            return ('【Q2】\nQuestion：本论文中所制备的材料为何性能优异？☘️第一，动态 B-O 键；☘️第二，链缠结。\n'
                    '【总之】\n总之，这项工作把冲击防护问题转化成了动态键设计问题。\n'
                    '【通俗理解】\n通俗地说：像一团遇急变硬的橡皮泥。\n'
                    '【标题】\n【Macromolecules】遇急变硬的硅硼弹性体：强度 12.5 MPa')
        return ''
    return chat


def test_骨架齐全_图由脚本放_数字回查_格式硬修():
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
    # 第一稿编的 77.7 被抓出来并重写掉；原文有的 12.5 / 4.1 / 15 不报
    assert st['unverified'] == [] and '77.7' not in content
    # 调用次数 = 导读 + 实验 + 每图两次（第一稿有编数）+ 收尾
    assert len(calls) == 1 + 1 + 2 * 2 + 1
    # 格式硬修：🌿/🍁 归位、英文冒号、问句钉回范式原话、「图 1」去空格、「▲ 图」合并、通俗理解起笔
    assert 'Question：各组分的作用是？🍁PDMS：柔性主链；🍁硼酸' in content
    assert '🌿180 °C 下加热 2 h；🌿氮气保护' in content and '（1）主要实验药品' in content
    assert '图 1，' not in content and '▲ 图' not in content
    assert '通俗理解：像一团' in content


def test_每栏只喂它该看的材料():
    calls = []
    sectioned.compose(MD, 'SI text: 5 kDa PDMS 0.5 g, 180 °C', FIGS, META, fake_chat(calls), log=lambda *a: None)
    lead, exp, exp2, f1, f1b, f2, f2b, wrap = calls
    assert '漏了材料里的这些数：4.1 MPa、0.5 g' in exp2['user']                # 清单先行：漏的点名补
    assert '【材料里出现的数值清单】' in exp['user'] and '5 kDa' in exp['user']
    assert 'Introduction' not in exp['user'] and 'Materials' not in lead['user'].split('【结论】')[1]
    assert 'boric acid' in exp['user'] and 'SI text' in exp['user']          # 实验栏拿到方法节 + SI
    assert '缩写：' in exp['user'] and 'PBS = polyborosiloxane' in exp['user']   # 术语表贯穿
    assert '找不到：77.7' in f1b['user']                                       # 数字回查的提示
    assert 'Figure 1.' in f1['user'] and 'Figure 2.' not in f1['user'].split('【正文里讨论它的段落】')[0]
    assert 'crossover at 15 rad/s' in f2['user'] and '797.4' not in f2['user']  # 参考文献不进材料
    assert '▲图1' in wrap['user'] and '▲图2' in wrap['user']                  # 收尾看的是已写好的深解


def test_综述按综述写():
    calls = []
    meta = dict(META, title='Recent advances in polyborosiloxane elastomers: a review')
    sectioned.compose(MD, '', FIGS, meta, fake_chat(calls), log=lambda *a: None)
    assert '系统总结了' in calls[0]['system']
    assert '主要材料体系' in calls[1]['system'] and '综述' in calls[-1]['system']


def test_清单先行_列清单与查漏():
    from shared.domain import numcheck as n
    must = n.must_numbers('droplets 19 μm, 46 μm (Fig. 2b); strain 1160% and 200 %; Tg 25 °C in 2024; Mn 1,500 g/mol; 0.50 MPa')
    assert must == ['19 μm', '46 μm', '1160 %', '200 %', '25 °C', '1,500 g/mol', '0.50 MPa']   # 年份不算数据；千分位认得出
    miss = n.missing_numbers('液滴 19 微米与 46 μm，应变 1160%，Tg 25 ℃，Mn 1500 g/mol，0.5 MPa', must)
    assert miss == ['200 %']            # 单位译成中文不算漏；0.50 与 0.5、1,500 与 1500 是同一个数
    assert n.checklist_block([]) == '' and '19 μm、46 μm' in n.checklist_block(must)


def test_数字回查的过滤():
    src = 'strength 12.5 MPa, 1 000 cycles, 2020 paper, Figure 3'
    bad = sectioned.unverified_numbers('图3 显示 12.5 MPa，1000 次循环，2020 年，第 5 组，3 种方法，缺 88.8 MPa', src)
    assert bad == ['88.8']


def test_无注裁图按顺序补号_目录图不补():
    from shared.domain.schema import outline as _ol
    ol = _ol.build_outline(MD)                       # 正文有 Figure 1、Figure 2 两条图注
    figs = [{'caption': ''}, {'caption': 'Figure 1. x'}, {'caption': ''}, {'caption': ''}]
    # 目录图（第 1 块）不补；第 3 块补成图 2；第 4 块超出图注总数不补
    assert sectioned.number_crops(figs, ol) == [(2, 1), (3, 2)]
    figs = [{'caption': 'Figure 1. x'}, {'caption': ''}, {'caption': 'Figure 3. y'}]
    ol3 = _ol.build_outline(MD + chr(10) * 2 + 'Figure 3. Third figure caption here.' + chr(10))
    assert sectioned.number_crops(figs, ol3) == [(1, 1), (2, 2), (3, 3)]   # 夹缝补 2


def test_分栏缓存_断点续跑只补缺的栏(tmp_path):
    cache = str(tmp_path / 'parts.json')
    calls = []
    sectioned.compose(MD, '', FIGS, META, fake_chat(calls), log=lambda *a: None, cache=cache)
    n1 = len(calls)
    calls2 = []
    content, _ = sectioned.compose(MD, '', FIGS, META, fake_chat(calls2), log=lambda *a: None, cache=cache)
    assert n1 > 0 and calls2 == [] and '## 通俗理解' in content       # 第二遍一次都不用调
    calls3 = []                                                        # 改了模型 = 指纹变了，缓存作废
    sectioned.compose(MD, '', FIGS, META, fake_chat(calls3), log=lambda *a: None, cache=cache, model='x')
    assert len(calls3) == n1


def test_图的段落认范围写法():
    assert sectioned._mentions('as shown in Figures 3 and 4, the', 4)
    assert sectioned._mentions('Figs. 2–5 show', 3)
    assert sectioned._mentions('(Fig. 3a–c)', 3)
    assert not sectioned._mentions('Figure S3 shows', 3)
    assert not sectioned._mentions('Fig. 13', 3)


def test_术语表():
    g = sectioned.glossary(MD + '\n\nSamples PBS-B12 and PBS-B12 and PBS-B12 were compared.')
    assert 'PBS = polyborosiloxane' in g and 'PBS-B12' in g


def test_没翻的英文长串():
    assert sectioned.untranslated('采用 Fourier-transform infrared spectroscopy 检测') == ['Fourier-transform infrared spectroscopy']
    assert sectioned.untranslated('样品 PDMS-IU-12 与 LiTFSI 的 SAXS 谱') == []          # 缩写与编号不算
    assert sectioned.untranslated('傅里叶变换红外光谱（FTIR）') == []


def test_收尾缺哪栏单补哪栏():
    calls = []

    def chat(system, user, purpose=None, model=None, temperature=0.3, max_tokens=None,
             thinking=None, provider=None):
        calls.append(user)
        if '只要你补写【Q2】' in user:
            return '【Q2】\nQuestion：本论文中所制备的材料为何性能优异？☘️第一，补上的。'
        # 正常调用永远漏掉 Q2
        return '【总之】\n总之，x。\n【通俗理解】\n通俗理解：y。\n【标题】\n【J】t'
    from shared.domain.schema import outline as _ol
    out = sectioned._wrap(chat, MD, _ol.build_outline(MD), META, ['▲图1，d'], False, '', MD, None, lambda *a: None)
    assert out['Q2'].startswith('Question：本论文中所制备的材料为何性能优异？☘️第一，补上的')
    assert sum(1 for u in calls if '只要你补写' in u) == 1      # 只补了缺的那一栏


def test_括号里的英文全称不算没翻译():
    p = '聚甲基丙烯酸甲酯（PMMA, poly(methyl methacrylate)）与 N-羟基琥珀酰亚胺（NHS, N-hydroxysuccinimide）'
    assert sectioned.untranslated(p) == [] and not sectioned._looks_english(p)
    assert sectioned.untranslated('图4，标题为"DFT calculations to show the feasibility of the radical"。') != []


def test_综述判定也看刊名():
    from shared.domain.schema import outline as _ol
    ol = _ol.build_outline(MD)
    assert sectioned.is_review_doc('Thermally conductive polymer composites', ol, 'Progress in Materials Science')
    assert not sectioned.is_review_doc('Thermally conductive polymer composites', ol, 'Macromolecules')


def test_一条图注都没认出来时按顺序对应():
    from shared.domain.schema import outline as _ol
    ol = _ol.build_outline(MD)                       # 正文 2 条图注
    assert sectioned.number_crops([{'caption': ''}, {'caption': ''}], ol) == [(1, 1), (2, 2)]
    assert sectioned.number_crops([{'caption': ''}] * 3, ol) == [(2, 1), (3, 2)]   # 多一块 = 目录图


def test_深解段漂到下一张图就截断():
    assert sectioned.untranslated('剪切增 stiffening 离子凝胶') == ['stiffening']
    assert sectioned.untranslated('损耗因子 tan δ 与 vdW 作用') == []


def test_渲染时转义尖括号():
    from tools.deepread.main_text import render_html
    h = render_html('## 讨论\n\n低压（<1×10^4 kPa^-1）下灵敏度 **高**\n\n图4，标题为"x"。')
    assert '（&lt;1×10^4' in h and '<strong>高</strong>' in h and '<p>图4，' in h
