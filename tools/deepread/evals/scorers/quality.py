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

# 材料文献的精读若没有带单位的数值，基本是空话。
_NUM_RE = re.compile(r'\d+(?:\.\d+)?\s*(?:%|nm|μm|um|mm|cm|kPa|MPa|GPa|Pa·s|'
                     r'°C|℃|K|g/mol|kJ|mol|wt%|s⁻¹|Hz|min|h)\b')


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
