# -*- coding: utf-8 -*-
"""evalset · 精读质量评测集基础件（公理：一份精读 → 可比较的质量记录）

**为什么需要它**：平台现有的 13 项体检全在验「能不能跑」，
**没有一项在验「跑出来的东西好不好」** —— 而后者才是用户真正在乎的。

那次「只贴了图没有文字」的废品，是用户自己翻到的，不是系统报的。
后来加的 `MIN_OK=3000` 只是单点防护：挡得住「没字」，挡不住「字很多但都是废话」。

## 本模块的真正目的（不只是攒分数）

单纯收集「好/差」用处有限 —— 改完精读逻辑重跑后，没人给新版本打分，
评测集会变成一次性的。

**真正的价值是：用用户的主观评分，校准出一个系统能自动算的质量分。**
所以每条评价都要连同当时精读的**客观快照**一起记：
字数、图数、有无具体数值、章节完整性、用的哪个模型。
等样本够了（8~10 条），就能分析「他说好的」和「他说差的」在客观指标上差在哪，
从此系统能自己判断质量退化，不用等人翻到。

对外接口：
  - snapshot(key)            → 某篇精读的客观指标快照
  - save(key, verdict, ...)  → 记录一条评价（含快照）
  - load() / get(key)        → 读评测集
  - pending(read_keys)       → 「读完了但还没评价」的清单
  - stats()                  → 好/差各多少、客观指标的差异
"""
import os, sys, re, json, time
from core import paths

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIBRARY = paths.LIBRARY
EVALSET = paths.evalset()

# 差评原因选项（用户在面板上勾选；以后从样本里归纳新的类别）
REASONS = [
    ('missing_data', '缺关键数据（没有具体数值/条件）'),
    ('too_vague', '太笼统，没有信息量'),
    ('figure_bad', '图不对、缺图、或图文不搭'),
    ('mechanism_wrong', '机理讲错了'),
    ('structure_bad', '结构混乱、重复啰嗦'),
    ('truncated', '明显被截断，没写完'),
]


def _summary_path(key):
    return os.path.join(LIBRARY, key, 'summary.html')


def snapshot(key):
    """算一份精读的客观指标。文件不存在返回 None。

    这些指标必须是**纯客观、可自动计算**的 —— 它们将来要替代人工评分。
    """
    p = _summary_path(key)
    if not os.path.exists(p):
        return None
    try:
        html = open(p, encoding='utf-8', errors='replace').read()
    except Exception:
        return None
    # **必须先剔除图片再算指标**：精读 HTML 里的图是 base64 内嵌的，
    # 那串编码里全是数字字母，不剔掉会把「数值密度」算成上万（实测 13471），
    # 而正文才 6641 字。**一个错的指标比没有指标更糟** —— 它会污染将来的校准。
    body = re.sub(r'<img[^>]*>', '', html)
    body = re.sub(r'<style[\s\S]*?</style>', '', body)
    body = re.sub(r'<script[\s\S]*?</script>', '', body)
    body = re.sub(r'<[^>]+>', ' ', body)          # 去标签，留纯文本
    text = re.sub(r'\s+', '', body)

    # 含具体数值的密度：材料文献的精读若没有数值，基本是空话
    nums = len(re.findall(r'\d+(?:\.\d+)?\s*(?:%|nm|μm|um|mm|cm|kPa|MPa|GPa|Pa·s|'
                          r'°C|℃|K|g/mol|kJ|mol|wt%|s⁻¹|Hz|min|h)\b', body))
    # 章节完整性：精读模板应有的几个部分
    sections = sum(1 for s in ('导读', '引言', '结果', '讨论', '机理', '总结', '文献信息')
                   if s in body)
    return {
        'chars': len(text),
        'figures': html.count('<img'),
        'numbers': nums,
        'sections': sections,
        'size_kb': round(os.path.getsize(p) / 1024),
        'mtime': time.strftime('%Y-%m-%d %H:%M',
                               time.localtime(os.path.getmtime(p))),
    }


def load():
    if not os.path.exists(EVALSET):
        return {}
    try:
        with open(EVALSET, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _write(data):
    tmp = EVALSET + '.tmp'
    os.makedirs(os.path.dirname(EVALSET), exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, EVALSET)      # 原子替换，避免写一半损坏评测集


def get(key):
    return load().get(key)


def save(key, verdict, reasons=None, note='', title=''):
    """记录一条评价。verdict: 'good' / 'bad'。

    **同时存下当时的客观快照** —— 这是本模块的关键：
    没有快照，评分就只是一个孤立的分数；有了快照，才能回答
    「什么样的客观特征对应着用户认为的好」。
    """
    if verdict not in ('good', 'bad'):
        raise ValueError("verdict 只能是 'good' 或 'bad'")
    data = load()
    data[key] = {
        'verdict': verdict,
        'reasons': list(reasons or []),
        'note': (note or '').strip()[:500],
        'title': title[:120],
        'snapshot': snapshot(key),
        'rated_at': time.strftime('%Y-%m-%d %H:%M'),
    }
    _write(data)
    return data[key]


def remove(key):
    data = load()
    if key in data:
        del data[key]
        _write(data)
        return True
    return False


def pending(read_keys):
    """「已读完但还没评价」的 key 列表。read_keys 来自 Zotero 的「读完」标签。"""
    done = load()
    return [k for k in read_keys if k not in done]


def stats():
    """好/差各多少，以及两组在客观指标上的差异。

    这是「用主观评分校准自动指标」的第一步 ——
    差异明显的指标，才是能拿来自动判质量的候选。
    """
    data = load()
    good = [v['snapshot'] for v in data.values()
            if v.get('verdict') == 'good' and v.get('snapshot')]
    bad = [v['snapshot'] for v in data.values()
           if v.get('verdict') == 'bad' and v.get('snapshot')]

    def avg(rows, field):
        vals = [r.get(field) or 0 for r in rows]
        return round(sum(vals) / len(vals), 1) if vals else None

    fields = ('chars', 'figures', 'numbers', 'sections')
    compare = {f: {'good': avg(good, f), 'bad': avg(bad, f)} for f in fields}

    # 差评原因统计：出现最多的，就是精读最该改进的地方
    reason_count = {}
    for v in data.values():
        for r in v.get('reasons') or []:
            reason_count[r] = reason_count.get(r, 0) + 1

    return {
        'total': len(data), 'good': len(good), 'bad': len(bad),
        'compare': compare,
        'reasons': sorted(reason_count.items(), key=lambda x: -x[1]),
        'ready': len(good) >= 3 and len(bad) >= 3,   # 样本够不够做校准
    }
