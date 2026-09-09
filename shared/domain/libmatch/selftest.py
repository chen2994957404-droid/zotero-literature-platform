# -*- coding: utf-8 -*-
"""libmatch 自测：纯逻辑，不联网、不碰用户数据。

测的是这块的三条承诺：
  ① 标题归一能吃掉排版差异（大小写/标点/空格/上下标残留）
  ② 判「我有没有」两条腿都认（DOI 或 归一标题），且不误伤
  ③ 相似度函数在脏输入下不抛异常（维度不一致、空、全零）
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.domain.libmatch import (
    DUP_SIM, STRONG_SIM, char_overlap, cosine, mark_have, norm_title)

_fail = []


def check(name, cond, extra=''):
    print(('  [PASS] ' if cond else '  [FAIL] ') + name + (('  ' + extra) if extra else ''))
    if not cond:
        _fail.append(name)


def main():
    print('libmatch 自测')

    # ① 标题归一
    a = norm_title('Poly(borosiloxane)s: Synthesis, and  Characterization')
    b = norm_title('POLY BOROSILOXANES synthesis and characterization')
    check('标题归一吃掉标点与大小写差异', a == b, f'{a[:28]}…')
    check('空标题归一成空串', norm_title(None) == '' and norm_title('') == '')

    # ② 我有没有
    have_t = {norm_title('Polyborosiloxanes (PBSs), Synthetic Kinetics')}
    have_d = {'10.1021/ma500632f'}
    papers = [
        {'title': 'Polyborosiloxanes (PBSs): Synthetic Kinetics', 'doi': ''},   # 标题命中
        {'title': '完全不同的一篇', 'doi': '10.1021/MA500632F'},                 # DOI 命中（大小写不同）
        {'title': '真的没有过的一篇', 'doi': '10.9999/x'},                        # 都不命中
    ]
    n = mark_have(papers, have_t, have_d)
    check('标题命中算「有」', papers[0]['in_library'] is True)
    check('DOI 命中且不分大小写', papers[1]['in_library'] is True)
    check('不命中的老实标 False', papers[2]['in_library'] is False)
    check('返回命中篇数', n == 2, f'n={n}')
    check('空输入不炸', mark_have([], set(), set()) == 0 and mark_have(None, set(), set()) == 0)

    # ③ 相似度在脏输入下不抛
    check('余弦：正常向量', abs(cosine([1, 0], [1, 0]) - 1.0) < 1e-9)
    check('余弦：正交为 0', abs(cosine([1, 0], [0, 1])) < 1e-9)
    check('余弦：全零不炸', cosine([0, 0], [0, 0]) == 0.0)
    check('余弦：维度不一致不炸', isinstance(cosine([1, 2, 3], [1]), float))
    check('重合度：完全相同为 1', abs(char_overlap('abcdefgh', 'abcdefgh') - 1.0) < 1e-9)
    check('重合度：空输入为 0', char_overlap('', 'abcd') == 0.0)
    check('重合度：太短的串不炸', isinstance(char_overlap('ab', 'ab'), float))

    # 阈值只是常数，但守住「顺序」这个语义
    check('判重阈值严于相关阈值', DUP_SIM > STRONG_SIM, f'{DUP_SIM} > {STRONG_SIM}')

    total = 15
    print(f'\n  {total - len(_fail)}/{total} 通过')
    return 1 if _fail else 0


if __name__ == '__main__':
    sys.exit(main())
