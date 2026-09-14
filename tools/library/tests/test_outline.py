# -*- coding: utf-8 -*-
"""骨架菜单：模型点菜的那一层（2026-09-08 加）。

**为什么要有它**：全文平均 5 万字符 ≈ 1.3 万 token，模型读三篇就把上下文吃掉一半，
而一个问题真正要看的往往是两三节。菜单几百 token，按地址取原文。

这一组全离线：造一份假的 full.md，不碰真实数据、不连 Zotero。
"""
import io
import json
import os

import pytest

from shared.domain.schema import outline as O
from shared.kernel import paths
from tools import library

MD = '''# A tough elastomer with dynamic bonds

Some author list here.

## Abstract

The material shows a tensile strength of 12.5 MPa and toughness of 88 MJ/m3.

## 1. Introduction

Zhang et al. reported 73.6 MPa for a similar system, far above earlier work.

## 2. Experimental section

### 2.1. Materials

PDMS (Mw = 1000 g/mol) and boric acid were used as received, 2.0 g each.

### 2.2. Mechanical property test

Tensile tests ran at 100 mm/min on a UTM with a 500 N load cell.

## 3. Results and discussion

### 3.1. Mechanical properties

The elastomer reaches 12.5 MPa with elongation at break of 850%, see Table 2.

### 3.2. Self-healing behaviour

Healing efficiency of 92% was achieved after 12 h at 25 C (Fig. 4).

## 4. Conclusion

A tough, healable elastomer was obtained.

## References

(1) Zhang, Y. J. Polym. Sci. 2020, 58, 1234-1245.
'''


@pytest.fixture
def paper(tmp_path, monkeypatch):
    """把 raw / curated 指到临时目录，写一份假全文。"""
    for name in ('RAW', 'CURATED'):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(paths, name, str(d))
    key = 'AAAA1111'
    os.makedirs(os.path.dirname(paths.fulltext(key)), exist_ok=True)
    io.open(paths.fulltext(key), 'w', encoding='utf-8').write(MD)
    return key


class Test骨架:
    def test_章节按功能归类(self, paper):
        got = {s['title'].split('.')[-1].strip()[:12]: s['kind']
               for s in library.outline(paper)['sections']}
        assert got['Introduction'] == O.BACKGROUND
        assert got['Materials'] == O.SYNTHESIS
        assert got['Mechanical p'] in (O.METHODS, O.RESULTS)   # 2.2 与 3.1 同名
        assert got['Conclusion'] == O.CONCLUSION
        assert got['References'] == O.NONBODY

    def test_引言被单独标出来(self, paper):
        """**这是硬错误的解药**：引言里的 73.6 MPa 是别人的数据。

        模型看得见「这一节是背景」，才有机会不把它当成本文的性能。
        """
        secs = library.outline(paper)['sections']
        bg = [s for s in secs if s['kind'] == O.BACKGROUND]
        assert bg and '73.6' in library.section(paper, bg[0]['id'])['text']

    def test_菜单只有骨架没有正文(self, paper):
        """菜单省 token 的原理就是这一条：**只报路，不带货**。

        （不测「菜单/全文」的比例：这份假论文只有 800 字符，比例没有意义；
        真实论文 4 万字符时菜单约 400 token，那个数字在 CLAUDE.md 里记着。）
        """
        menu = library.render_outline(library.outline(paper))
        assert '92%' not in menu and '73.6' not in menu, '菜单里不该有正文数据'
        assert 'Self-healing behaviour' in menu and 's9' in menu, '但要报得出路'

    def test_按地址取的是那一节而不是整篇(self, paper):
        o = library.outline(paper)
        sec = [s for s in o['sections'] if 'Self-healing' in s['title']][0]
        t = library.section(paper, sec['id'])['text']
        assert '92%' in t and 'Introduction' not in t

    def test_地址错了要告诉模型有哪些可用(self, paper):
        r = library.section(paper, 's999')
        assert r['chars'] == 0 and 's1' in r['why_empty']

    def test_没解析过的文献不是错误(self, paper):
        r = library.outline('BBBB2222')
        assert r['available'] is False and '解析' in r['why']


class Test缓存:
    def test_算过一次就缓存(self, paper):
        assert library.outline(paper)['cached'] is False
        assert library.outline(paper)['cached'] is True
        assert os.path.exists(paths.outline(paper))

    def test_全文变新了要重算(self, paper):
        library.outline(paper)
        os.utime(paths.fulltext(paper), None)      # 假装重新解析过
        import time
        time.sleep(0.01)
        os.utime(paths.fulltext(paper), None)
        assert library.outline(paper)['cached'] is False

    def test_缓存坏了不影响这次调用(self, paper):
        library.outline(paper)
        io.open(paths.outline(paper), 'w', encoding='utf-8').write('{坏的')
        assert library.outline(paper)['available'] is True


# ── 2026-09-13 加细：段 / 表 / 图注 三种地址 ─────────────────────────
LONG_MD = '''# Paper

## 1. Introduction

short intro.

## 2. Results

''' + '\n\n'.join(
    'Paragraph %d about tensile strength of %d MPa and a lot of filler text %s.' % (i, 10 + i, 'x' * 400)
    for i in range(1, 12)) + '''

![](images/abc.jpg)

![](images/def.jpg)

Figure 2 | Stress-strain curves of the three gels. a, alginate; b, hybrid.

Table 1. Mechanical properties of samples.

<table><tr><td>Sample</td><td>Strength (MPa)</td><td>Strain (%)</td></tr>
<tr><td>PBS-1</td><td>12.5</td><td>850</td></tr>
<tr><td>PBS-2</td><td>15.1</td><td>620</td></tr></table>

## 3. Conclusion

done.
'''


def test_长节列到段_短节不列():
    o = O.build_outline(LONG_MD)
    by = {s['title']: s for s in o['sections']}
    res, intro = by['2. Results'], by['1. Introduction']
    assert res['chars'] > O.LONG_SECTION and res.get('paras'), '超过阈值的节要有段地址'
    assert not intro.get('paras'), '短节一口气读完，不切'
    ids = [p['id'] for p in res['paras']]
    assert ids[0] == res['id'] + '.p1' and 3 <= len(ids) < 11,         '相邻自然段攒到 PARA_TARGET 才算一个地址：11 段 470 字的该并成三四块，不是 11 个地址'
    assert all(p['chars'] >= O.MIN_PARA for p in res['paras']), '太短的块该并进邻段'


def test_图片标记不单独成段():
    o = O.build_outline(LONG_MD)
    res = next(s for s in o['sections'] if s['title'] == '2. Results')
    heads = [p['head'] for p in res['paras']]
    assert not any(h.startswith('![](') for h in heads), '一行 `![](images/…)` 不是一段'


def test_按段地址取到的不重不漏():
    o = O.build_outline(LONG_MD)
    res = next(s for s in o['sections'] if s['title'] == '2. Results')
    texts = [O.section_text(LONG_MD, o, p['id']) for p in res['paras']]
    for i in range(1, 12):
        hits = [t for t in texts if 'Paragraph %d ' % i in t]
        assert len(hits) == 1, '每个自然段恰好落在一个地址里'
    p2 = O.section_text(LONG_MD, o, res['paras'][1]['id'])
    assert 'Paragraph 1 ' not in p2, '第二块不该包含第一块的内容'


def test_无编号小标题挂在最近的编号章节下():
    """`2. RESULTS AND DISCUSSION` 后面跟无编号的 `Accelerating Exchange`：
    markdown 里同级，逻辑上是子节，该继承「结果」（全库实测一篇 17823 字的结果节成了未分类）。"""
    md = '''# T

## 1. INTRODUCTION

intro text here.

## 2. RESULTS AND DISCUSSION

overview.

## Accelerating Exchange

tensile strength 12 MPa.

## Accelerating Dissociation

more results.

## 3. CONCLUSIONS

done.
'''
    o = O.build_outline(md)
    kinds = {s['title']: s['kind'] for s in o['sections']}
    assert kinds['Accelerating Exchange'] == O.RESULTS
    assert kinds['Accelerating Dissociation'] == O.RESULTS
    assert kinds['3. CONCLUSIONS'] == O.CONCLUSION, '编号章节仍然是兄弟，不该被拽成子节'


def test_引言与结论之间认不出的章节标成主体():
    """综述 / Nature 式描述性小标题：按位置标「主体」，比「未分类」诚实一步；
    但引言前、结论后的仍然是「未分类」（位置上就不是正文中段）。"""
    md = '''# T

## Some odd header

x.

## Introduction

intro.

## SSG Dampers

dampers.

## SSG Sensors

sensors.

## Conclusions and Perspectives

done.

## Another odd header

y.
'''
    o = O.build_outline(md)
    kinds = {s['title']: s['kind'] for s in o['sections']}
    assert kinds['SSG Dampers'] == O.BODY and kinds['SSG Sensors'] == O.BODY
    assert kinds['Some odd header'] == O.UNKNOWN and kinds['Another odd header'] == O.UNKNOWN


def test_表有地址_取回整张HTML():
    o = O.build_outline(LONG_MD)
    assert len(o['tables']) == 1
    t = o['tables'][0]
    assert t['id'] == 't1' and t['n_rows'] == 3 and t['n_cols'] == 3
    assert 'Mechanical properties' in t['caption'] and t['section']
    html = O.section_text(LONG_MD, o, 't1')
    assert html.startswith('<table') and 'PBS-2' in html


def test_图注有地址_只取图注不含图():
    o = O.build_outline(LONG_MD)
    assert [f['ref'] for f in o['figures']] == ['Figure 2']
    txt = O.section_text(LONG_MD, o, 'f1')
    assert txt.strip().startswith('Figure 2') and '![](' not in txt


def test_图注挤在上一段后面也认得出():
    # MineRU 的真实形状：上一段 + 图片行（两空格换行，无空行）+ 图注，三者一个块
    md = ('# T\n\n## 3. Results\n\nThe curves show 4.1 MPa.\n'
          '![](images/a.jpg)  \nFigure 5. Mechanical properties. (A) Stress–strain curves.\n\n'
          'Next paragraph.\n')
    o = O.build_outline(md)
    assert [f['ref'] for f in o['figures']] == ['Figure 5']
    txt = O.section_text(md, o, 'f1')
    assert txt.strip().startswith('Figure 5') and 'curves show' not in txt


def test_菜单列出段表图_且仍然只报路不带货():
    o = O.build_outline(LONG_MD)
    m = O.menu(o)
    assert 's2.p1' in m or 's3.p1' in m
    assert 't1 [Table 1]' in m and 'f1 [Figure 2]' in m
    assert '12.5' not in m, '表里的数据不许出现在菜单里'
    assert len(m) < len(LONG_MD) * 0.25


def test_地址错了列出全部可点的():
    o = O.build_outline(LONG_MD)
    assert O.section_text(LONG_MD, o, 's99') == '' and O.section_text(LONG_MD, o, 't9') == ''
    ids = O.addresses(o)
    assert 't1' in ids and 'f1' in ids and any('.p' in i for i in ids)


def test_整块是表的不再当一段():
    o = O.build_outline(LONG_MD)
    res = next(s for s in o['sections'] if s['title'] == '2. Results')
    assert not any(p['head'].startswith('<table') for p in res['paras']), '表有自己的地址 t1'


def test_段地址不重复():
    """结尾攒下的一块曾经固定叫 p1，和第一段撞号（2026-09-14 真实骨架里看到两个 s12.p1）。"""
    md = '## 1. Results\n\n' + '\n\n'.join('Para %d %s.' % (i, 'z' * 1300) for i in range(1, 5)) + '\n\nShort tail paragraph that stands alone at the end with enough characters to count as a block.\n'
    o = O.build_outline(md)
    ids = [p['id'] for p in o['sections'][0]['paras']]
    assert len(ids) == len(set(ids)), ids
    assert ids == ['s1.p%d' % i for i in range(1, len(ids) + 1)]
