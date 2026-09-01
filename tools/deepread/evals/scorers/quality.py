# -*- coding: utf-8 -*-
"""精读质量的客观指标（纯函数，不碰文件系统）。

**这些指标将来要替代人工评分**，所以它们必须是纯客观、可自动算的。
`metrics()` 拿到 HTML 字符串就能算 —— 不需要真实文献、不需要磁盘，
于是它可以被毫秒级地测试，也可以拿历史 HTML 回溯打分。
"""
import os
import re
import time

# 精读模板应有的栏目。少一个就是模型没按范式写。
SECTIONS = ('导读', '引言', '结果', '讨论', '机理', '总结', '文献信息')

# 指标口径的版本号。**改了任何一条算法就 +1。**
#
# 为什么必须有：快照是存进 `evalset.json` 的历史数据，用来将来做「主观评分 ↔
# 客观指标」的校准。口径一变，旧快照和新算的就不可比了 —— 而这种不可比
# **不会报错**，只会让校准悄悄建立在两把不同的尺子上。
# 有了版本号，`evals.stats()` 能一眼看出「这些数是两把尺子量出来的」，
# `evals.recompute()` 能把旧的重算齐。
METRICS_VER = 2

# 材料文献的精读若没有带单位的数值，基本是空话。
#
# ⚠ 分成两组是有原因的（v1 → v2 修的就是这个）：
#   · 以字母结尾的单位（MPa、nm、min…）需要 `\b`，否则 "5 min" 会匹配 "5 mi" 之类
#   · **以符号结尾的单位（%、℃、°C、wt%…）绝不能加 `\b`** ——
#     `\b` 要求后面紧跟词字符，而中文正文里 "800 %" 后面通常是「，」或空格，
#     于是整整一类百分数**从来没被数进去过**。
#     实测「拉伸强度 12 MPa，断裂伸长率 800 %」v1 只数出 1 处，v2 数出 2 处。
#   百分数在材料文献里恰恰是最常见的一类数值（伸长率、修复效率、保持率），
#   漏掉它等于这个指标一直在低估「有没有真数据」。
_UNITS_WORD = r'nm|μm|um|mm|cm|kPa|MPa|GPa|K|g/mol|kJ|mol|Hz|min|h'
_UNITS_SYMBOL = r'wt%|Pa·s|°C|℃|s⁻¹|%'          # 长的排前面，别让 `%` 先吃掉 `wt%`
_NUM_RE = re.compile(r'\d+(?:\.\d+)?\s*(?:(?:' + _UNITS_WORD + r')\b'
                     r'|(?:' + _UNITS_SYMBOL + r'))')


def metrics(html):
    """一段精读 HTML → {chars, figures, numbers, sections}。纯函数。

    **必须先剔除图片再算**：精读 HTML 里的图是 base64 内嵌的，
    那串编码里全是数字字母，不剔掉会把「数值密度」算成上万（实测 13471），
    而正文才 6641 字。**一个错的指标比没有指标更糟** —— 它不会报错，
    只会安静地污染将来的校准。
    """
    body = re.sub(r'<img[^>]*>', '', html)
    body = re.sub(r'<style[\s\S]*?</style>', '', body)
    body = re.sub(r'<script[\s\S]*?</script>', '', body)
    body = re.sub(r'<[^>]+>', ' ', body)          # 去标签，留纯文本
    text = re.sub(r'\s+', '', body)
    return {
        'chars': len(text),
        'figures': html.count('<img'),
        'numbers': len(_NUM_RE.findall(body)),
        'sections': sum(1 for s in SECTIONS if s in body),
        'metrics_ver': METRICS_VER,      # 这份数是用哪把尺子量的
    }


def snapshot_file(path):
    """给一份精读 HTML 的路径，算完整快照（含文件大小与时间）。不存在返回 None。"""
    if not os.path.exists(path):
        return None
    try:
        html = open(path, encoding='utf-8', errors='replace').read()
    except OSError:
        return None
    snap = metrics(html)
    snap['size_kb'] = round(os.path.getsize(path) / 1024)
    snap['mtime'] = time.strftime('%Y-%m-%d %H:%M',
                                  time.localtime(os.path.getmtime(path)))
    return snap
