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
