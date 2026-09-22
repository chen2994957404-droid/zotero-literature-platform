# -*- coding: utf-8 -*-
"""范文分栏（人写的，靠标记词）：单元研究（evals/units）与审稿校准（review）共用。

范式里的固定起笔：近期(导读) / (1)主要实验药品(实验) / Question(Q1/Q2) / 图N(图) / 总之 / 通俗理解。
"""
import re

# 范文栏 → 精读栏 key（compose 缓存那套），审稿按 key 挑原文材料
COLUMN_KEY = {'导读': 'lead', '引言': 'lead', '实验': 'exp', 'Q1': 'exp', '图': 'fig:0', 'Q2': 'wrap', '总之': 'wrap',
              '通俗理解': 'skip', '文献信息': 'skip'}
_FIGNO = re.compile(r'^[▲▼]?\s*图\s*(\d+)')


def column_of(para, prev):
    """范文段落 → 栏名。"""
    p = para.strip()
    if p.startswith('近期') or '报道了' in p[:60] or '系统总结了' in p[:60]:
        return '导读'
    if re.match(r'^[（(]?1[）)]?\s*主要实验药品|^[（(]1[）)]', p) or p.startswith('主要实验药品'):
        return '实验'
    if p.startswith('Question') or p.startswith('问题'):
        return 'Q2' if '性能' in p[:40] and '优异' in p[:60] else 'Q1'
    if _FIGNO.match(p) or re.match(r'^\[?Fig', p, re.I):
        return '图'
    if p.startswith('总之'):
        return '总之'
    if p.startswith('通俗理解'):
        return '通俗理解'
    if p.startswith('文献信息') or p.startswith('DOI') or p.startswith('原文链接'):
        return '文献信息'
    if prev in ('导读',) and len(p) > 60:
        return '引言'
    return prev if prev and prev != '文献信息' else '引言'      # 文献信息不粘：老版式头部就有 DOI 行，粘上整篇就没了


def figure_no(para):
    m = _FIGNO.match(para.strip())
    return int(m.group(1)) if m else None


def reference_sections(ref_text):
    """范文 → [(栏 key, 栏名, 文本)]，与 review.sections_of 同形状：图按图号各成一栏（fig:<n>），其余按栏合并相邻段。"""
    body = ref_text.split('\n---\n', 1)[1] if '\n---\n' in ref_text else ref_text
    out, cur, buf = [], None, []

    def flush():
        if cur and buf and cur[0] != 'skip':
            out.append((cur[0], cur[1], '\n'.join(buf)))
        buf.clear()

    col = ''
    for raw in body.split('\n'):
        p = raw.strip()
        if not p or p.startswith('![') or p.startswith('#') or p.startswith('来源:') or p.startswith('---'):
            continue
        if re.match(r'^\d+\.\s*\d*$', p) or p in ('引言', '实验', '讨论', '总结', '结论'):
            continue
        col = column_of(p, col)
        key = COLUMN_KEY.get(col, 'wrap')
        if col == '图':
            n = figure_no(p)
            if n is not None:
                key = 'fig:%d' % n
            elif cur and cur[0].startswith('fig:'):
                key = cur[0]
        if cur is None or key != cur[0]:
            flush()
            cur = (key, col)
        buf.append(p)
    flush()
    merged = []
    for k, name, text in out:
        if merged and merged[-1][0] == k:
            merged[-1] = (k, merged[-1][1], merged[-1][2] + '\n' + text)
        else:
            merged.append((k, name, text))
    return merged
