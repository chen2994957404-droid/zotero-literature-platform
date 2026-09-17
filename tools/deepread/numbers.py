# -*- coding: utf-8 -*-
"""带单位的数：从材料里列清单、查精读写了没写（2026-09-17，「清单先行」）。

**为什么要有它**：金标评测里最弱的一项一直是「数字覆盖」（范文里带单位的数我们写了几成，
40 篇中位 0.79）。原来的数字回查只管「别编」——写出来的数必须在原文里有；
**没人管「别漏」**。小模型的毛病恰恰是概括：看见十个数写六个。
所以改成：生成之前先把这一栏材料里的数列成清单塞进提示词，生成之后查覆盖，漏的点名补。

**同一把尺子**：这里的正则与 `evals/scorers/golden.py` 的「数字覆盖」共用一份 ——
否则流水线认为「都写了」、评测认为「漏了一半」，两边永远对不上。评分器从这里 import。

纯函数，不联网、不读盘。
"""
import re

# 数值 + 单位。单位表按范文（774 对推送）里出现频次排的，`(?![A-Za-z])` 挡住 "5 sec" 里的 s 匹配到 "sec"。
NUM_UNIT = re.compile(r'(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?:wt%|vol%|mol%|%|℃|°C|kPa|MPa|GPa|Pa·s|Pa|nm|μm|um|mm|cm|'
                      r'kJ|J|mol|Hz|kHz|min|h|s⁻¹|s|g/mol|kDa|Da|mg|g|mL|L|V|mA|W|K|°)(?![A-Za-z])')

# 不算数据的数：单个位数（"3 h" 这种也算数据，所以只在**没单位**时才滤，这里都有单位，不滤）、年份。
_YEAR = re.compile(r'^(19|20)\d\d$')


def norm(value):
    """'19.50' → '19.5'，'1,500' → '1500'：两边比较前统一（MineRU 常把 1 000 拆开，比较时空格也去掉）。"""
    value = value.replace(',', '')
    return value.rstrip('0').rstrip('.') if '.' in value else value


def must_numbers(text, cap=30):
    """材料 → 按出现顺序去重的「数值+单位」清单，例如 ['19 μm', '1160 %', '0.5 MPa']。

    `cap` 是上限：一栏写几百字装不下一百个数，清单太长反而让模型顾此失彼。
    超了按出现顺序截（材料本身就是按重要性组织的：图注在前、正文段落在后）。
    """
    out, seen = [], set()
    for m in NUM_UNIT.finditer(text or ''):
        v = norm(m.group(1))
        if v in seen or _YEAR.match(v):
            continue
        seen.add(v)
        out.append('%s %s' % (m.group(1), m.group(0)[len(m.group(1)):].strip()))
        if len(out) >= cap:
            break
    return out


def missing_numbers(text, must):
    """清单里哪些数在精读文字里没出现（只比数值，不比单位 —— 单位常被译成中文）。"""
    body = re.sub(r'[\s,]', '', text or '')
    miss = []
    for item in must:
        v = norm(item.split(' ', 1)[0])
        if v not in body:
            miss.append(item)
    return miss


def checklist_block(must):
    """塞进提示词末尾的那一段。空清单给空串。"""
    if not must:
        return ''
    return ('\n\n【材料里出现的数值清单】（下面每一个都要写进正文对应的句子里，带上它的对象与样品编号；'
            '实在写不下的按重要性取舍，但绝不许编造清单以外的数）\n' + '、'.join(must))
