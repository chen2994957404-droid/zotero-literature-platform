# -*- coding: utf-8 -*-
"""scan · 用**脚本**从全文里扫出「数值 + 单位 + 出处 + 上下文」。不调模型。

**为什么要有这一步**（用户 2026-09-07 的判断）：
「这个工作是不是对大模型的智力要求不高……能用脚本做的应该先用脚本实现。」

拆开看，一条测量里真正需要「理解」的只有一小部分：

| 要素 | 谁能做 |
|---|---|
| 数值、单位、大于小于、区间 | **正则**（本模块）|
| 它印在表几图几 | **脚本**：数字附近就写着 `Table 2`；markdown 里表格还有结构 |
| 它是什么性能 | 词表能命中大半（`PROPERTY_ALIASES`），剩下的才要模型 |
| 它属于哪个样品 | 要理解上下文 → 模型（但输入短、选项封闭，小模型够） |
| 材料体系 / 机理 / 应用 | 要归纳 → 这才是该花钱的地方 |

**脚本抓的出处有一个模型给不了的性质：它不可能是编的。**
数字和 `Table 2` 是同一段文字里的两个位置，程序只是把它们连起来。
今天全库 600 多条数字没有出处，根子就在这一步交给了模型。

对外接口：
  - `scan_numbers(md, window=90)` → 候选列表，每条带 value/unit/raw/context/
    location/section/in_table
  - `nearest_ref(md, pos)` → 这个位置最近的 `Table N` / `Fig. N`

**它不产出「测量」，只产出候选**。谁是哪个样品的哪个性能，那一步在上层。
"""
import re

from . import parse_property, normalize_property_name

# 单位表：写全一点，宁可多抓（上层还会筛），也别漏掉整类性能。
# 顺序有讲究：长的在前，否则 'MPa' 会被 'Pa' 先吃掉。
_UNITS = [
    'GPa', 'MPa', 'kPa', 'Pa·s', 'Pa s', 'Pa',
    'kJ/m2', 'kJ/m\\^2', 'kJ m-2', 'J/m2', 'J m\\^-2', 'J/g', 'kJ/mol',
    'g/mol', 'kg/mol', 'kDa', 'Da',
    'S/cm', 'S/m', 'mS/cm', 'µS/cm', 'uS/cm',
    'wt%', 'wt.%', 'wt %', 'vol%', 'mol%', '%',
    '°C', '℃', 'K', 'h', 'min', 's-1', 's\\^-1', 'rad/s', 'Hz', 'rpm',
    'mm/min', 'mm min-1', 'mm', 'µm', 'um', 'nm', 'cm', 'm',
    'mmol', 'mol/g', 'mol', 'mg', 'kg', 'g', 'mL', 'L',
    'cm3/g', 'm2/g', 'g/cm3', 'g cm-3',
]
_UNIT_RE = '|'.join(re.escape(u).replace('\\\\', '\\') for u in _UNITS)

# 数：支持 1.2e5 / 1.2×10^4 / 区间 / 前缀比较符
_NUM = r'[-+]?\d+(?:[.,]\d+)?(?:\s*[eE][-+]?\d+|\s*[×xX]\s*10\s*\^?\s*[-+−]?\d+)?'
_VALUE_RE = re.compile(
    r'(?P<cmp>[~≈><≥≤]|\bup to\b|\babout\b|\bover\b)?\s*'
    r'(?P<num>' + _NUM + r'(?:\s*[–—~-]\s*' + _NUM + r')?)\s*'
    r'(?P<unit>' + _UNIT_RE + r')(?![A-Za-z])')

_REF_RE = re.compile(r'(?i)\b(table|tab\.|figure|fig\.|fig|scheme)\s*([SIVX]?\d+[a-z]?)')
_HEAD_RE = re.compile(r'(?m)^(#{1,4})\s+(.+)$')
# markdown 表格行：`| a | b |`
_TABLE_ROW = re.compile(r'^\s*\|.*\|\s*$')


def _sections(md):
    """[(起始位置, 标题), ...]，用来说「这个数字出现在哪一节」。"""
    return [(m.start(), m.group(2).strip()) for m in _HEAD_RE.finditer(md)]


def _section_at(sections, pos):
    cur = ''
    for start, title in sections:
        if start > pos:
            break
        cur = title
    return cur


def nearest_ref(md, pos, back=600, fwd=300):
    """这个位置最近的表号/图号。**先往前找**（"如表 2 所示，强度为 …"更常见）。

    找不到就返回空串 —— 空出处是事实，编一个才是错。
    """
    left = md[max(0, pos - back):pos]
    hits = list(_REF_RE.finditer(left))
    if hits:
        m = hits[-1]
        return _fmt_ref(m)
    m = _REF_RE.search(md[pos:pos + fwd])
    return _fmt_ref(m) if m else ''


def _fmt_ref(m):
    kind = m.group(1).lower().rstrip('.')
    kind = 'Table' if kind.startswith('tab') else (
        'Fig.' if kind.startswith('fig') else 'Scheme')
    return '%s %s' % (kind, m.group(2))


def scan_numbers(md, window=90, limit=4000):
    """全文 → 数值候选列表。每条：

        {value, value_max, unit, cmp, raw, context, section, location, in_table, pos}

    `raw` 是「上下文里挑出来的名字 + 值」的粗拼，供上层归一；
    `location` 是脚本定位到的表号/图号（**不可能是编的**）。
    """
    if not md:
        return []
    sections = _sections(md)
    lines = md.splitlines(keepends=True)
    # 每行起始偏移，用来判断这一行是不是 markdown 表格行
    offs, acc = [], 0
    for ln in lines:
        offs.append((acc, acc + len(ln), _TABLE_ROW.match(ln) is not None))
        acc += len(ln)

    out = []
    for m in _VALUE_RE.finditer(md):
        pos = m.start()
        ctx = md[max(0, pos - window):min(len(md), m.end() + 30)].replace('\n', ' ')
        parsed = parse_property('%s %s' % (m.group('num'), m.group('unit')))
        in_table = False
        for a, b, is_row in offs:
            if a <= pos < b:
                in_table = is_row
                break
        out.append({
            'value': parsed['value'], 'value_max': parsed['value_max'],
            'unit': m.group('unit'), 'cmp': (m.group('cmp') or '').strip(),
            'raw': m.group(0).strip(), 'context': ctx.strip(),
            'section': _section_at(sections, pos),
            'location': nearest_ref(md, pos), 'in_table': in_table, 'pos': pos,
        })
        if len(out) >= limit:
            break
    return out


def guess_property(context):
    """从上下文里猜这是什么性能 —— **只认词表，认不出就留空**。

    认不出不是失败：那正是该交给模型的那一小部分。
    """
    low = context.lower()
    best, best_pos = '', None
    for canon, aliases in _PROP_HINTS:
        for a in aliases:
            i = low.rfind(a)
            if i >= 0 and (best_pos is None or i > best_pos):
                best, best_pos = canon, i
    return best


def _hints():
    from . import PROPERTY_ALIASES
    return sorted(((canon, tuple(a.lower() for a in aliases))
                   for canon, aliases in PROPERTY_ALIASES.items()),
                  key=lambda kv: -max(len(a) for a in kv[1]))


_PROP_HINTS = _hints()


def scan_measurements(md, window=90):
    """候选 → 「能进测量层的那些」：认得出性能名、且拆得出数的。

    归属哪个样品这里**不猜** —— 那要理解上下文，是模型的活。
    """
    out = []
    for c in scan_numbers(md, window=window):
        name = guess_property(c['context'])
        if not name or c['value'] is None:
            continue
        out.append({'sample_id': '', 'name': normalize_property_name(name),
                    'raw_name': name, 'value': c['value'],
                    'value_max': c['value_max'], 'unit': c['unit'],
                    'cmp': c['cmp'], 'condition': '', 'location': c['location'],
                    'section': 'main', 'method': 'script', 'raw': c['raw'],
                    'context': c['context']})
    return out
