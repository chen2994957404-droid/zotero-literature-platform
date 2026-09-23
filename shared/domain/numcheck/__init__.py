# -*- coding: utf-8 -*-
"""numcheck · 数字的三件事：列清单（别漏）、查覆盖（漏了哪些）、查来源（别编）。

住在 `shared/domain/`（纯逻辑层）：不联网、不读盘、不知道文件在哪。
使用者 ≥2（精读 `tools/deepread`、问答 `tools/ask`）—— 这是它配住 shared 的理由（硬规则 1）。

## 为什么有它（2026-09-17，「清单先行」）

**为什么要有它**：金标评测里最弱的一项一直是「数字覆盖」（范文里带单位的数我们写了几成，
40 篇中位 0.79）。原来的数字回查只管「别编」——写出来的数必须在原文里有；
**没人管「别漏」**。小模型的毛病恰恰是概括：看见十个数写六个。
所以改成：生成之前先把这一栏材料里的数列成清单塞进提示词，生成之后查覆盖，漏的点名补。

**同一把尺子**：精读评测器（`tools/deepread/evals/scorers/golden.py`）的「数字覆盖」也从这里 import 正则 ——
否则流水线认为「都写了」、评测认为「漏了一半」，两边永远对不上。

| 函数 | 干什么 |
|---|---|
| `must_numbers(text, cap)` | 材料 → 按出现顺序去重的「数值+单位」清单 |
| `missing_numbers(text, must)` | 清单里哪些数在产出里没出现（只比数值） |
| `checklist_block(must)` | 塞进提示词末尾的那段话 |
| `unverified_numbers(content, source)` | 产出里出现、来源里找不到的数（别编） |
| `data_numbers(text)` | 一段话里「算数据」的数（滤掉图号 / 年份 / 单个位数） |
| `ungrounded_numbers(claim, source)` | 比上一条严：完整数字比、带单位的连单位一起比（审稿的脚本数字闸） |
| `norm_source(text)` | 原文去 LaTeX 排版符号、统一 μ / ℃ 写法，给上面两条比数用 |
| `grounded_together(text, source, window)` | 这句的 ≥2 个数在来源里**挨在一起**出现（审稿用来否决「原文没有」的误判） |
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


# 与 NUM_UNIT 不同：这里抓**所有**数，不要求带单位 —— 编的数往往没单位。
_ANY_NUM = re.compile(r'(?<![\d.])(\d+(?:\.\d+)?)(?!\d)')


def data_numbers(text):
    """一段话里「算数据」的数，按出现顺序去重。

    过滤掉不是"数据"的数：图号/表号/第几/年份/单个位数（"3 种方法"这种）、后面紧跟小写字母的（"4a" 是子图）。
    """
    text = text or ''
    out = []
    for m in _ANY_NUM.finditer(text):
        s = m.group(1)
        pre = text[max(0, m.start() - 2):m.start()]
        if s in out or re.search(r'[图表第（(]$', pre) or re.search(r'^[a-z]', text[m.end():m.end() + 1]):
            continue
        if '.' not in s and (len(s) < 2 or (len(s) == 4 and s.startswith(('19', '20')))):
            continue
        out.append(s)
    return out


def unverified_numbers(content, source):
    """产出里出现、来源（原文 / 检索片段）里找不到的数。**只报不改**：给重写提示和评测用。

    来源去掉空格与千分位逗号再比 —— MineRU 常把 `1 000` 拆开。
    """
    src = re.sub(r'[\s,]', '', source or '')
    return [s for s in data_numbers(content)
            if s not in src and s.rstrip('0').rstrip('.') not in src]


def norm_source(text):
    """原文 → 便于比数的一串：去空白 / 千分位 / LaTeX 排版符号，μ 与 ℃ 统一写法。

    MineRU 出的全文里数和单位常是公式：`$20~^{\\circ}\\mathrm{C}$`、`10\\mu m`；µ（U+00B5）和 μ 是两个字。
    不统一的话「数字 + 单位」一比就大面积误伤（2026-09-22 主力机 10 篇实测：误伤 4.0% → 统一后 0.9%）。
    """
    t = (text or '').replace('µ', 'μ').replace(r'\mu', 'μ').replace(r'^{\circ}', '°')
    t = t.replace(r'\circ', '°').replace(r'\%', '%')
    t = re.sub(r'\\(mathrm|mathbf|text|rm)\s*', '', t)
    t = re.sub(r'[\s,~${}\\]', '', t)
    return t.replace('℃', '°C')


_UNIT_AFTER = re.compile(r'\s*(wt%|vol%|mol%|%|℃|°C|kPa|MPa|GPa|Pa|nm|μm|µm|mm|cm|kJ|J|mol|Hz|min|h|s|kDa|mg|g|mL|L|V|W|K|'
                         r'小时|分钟|秒|天)')
_UNIT_ALIAS = {'℃': '°C', 'µm': 'μm', '小时': 'h', '分钟': 'min', '秒': 's', '天': 'd'}


def ungrounded_numbers(claim, source):
    """一句话里、原文（含 SI）里找不到的数 —— 比 `unverified_numbers` 严，给审稿的脚本数字闸用（2026-09-22）。

    两处更严，都是主力机 10 篇范文实测定的（干净句 865、塞错 80 处）：
      · 数按**完整数字**比：17 不算出现在 2017 / 170 / 17.5 里（改数抓到 16 → 25 / 50）
      · 句里的数后面紧跟单位时，原文里要有**同一个数紧跟同一个单位**（单位写法先统一）
        —— 编造句「150 °C 老化 72 h 保持 93%」里的每个数单拎出来原文多半都有，连着单位就没有了
        （改数 25 → 34 / 50，编造句 11 → 25 / 30；干净范文误伤 0.9%，逐条看多是范文自己换算的数）
    """
    c = re.sub(r'(?<=\d),(?=\d{3}(?!\d))', '', claim or '').replace('µ', 'μ')     # 10,000 是一个数
    src = norm_source(source)
    nums = data_numbers(c)
    out = []
    for n in nums:
        alts = {n, n.rstrip('0').rstrip('.') if '.' in n else n}
        if not any(re.search(r'(?<![\d.])%s(?!\.?\d)' % re.escape(a), src) for a in alts):
            out.append(n)
    for m in _ANY_NUM.finditer(c):
        n = m.group(1)
        if n in out or n not in nums:
            continue
        um = _UNIT_AFTER.match(c, m.end())
        if not um:
            continue
        u = _UNIT_ALIAS.get(um.group(1), um.group(1))
        if not re.search(r'(?<![\d.])%s(?!\.?\d)%s' % (re.escape(n), re.escape(u)), src):
            out.append(n)
    return out


def grounded_together(text, source, window=600):
    """这句话里的数（至少两个）在来源里能不能在**同一处**（前后 `window` 字符内）全部找到。

    审稿用（2026-09-22）：本地模型会对「证据就在材料里」的句子判「原文没有」（规划 §十四补）。
    两个以上的数在原文同一处凑齐，偶然撞上的可能很小 —— 这时「原文没有」一定是误判。
    只有一个数的句子不下这个结论（常见数到处都有）。数的前后不许紧挨数字，免得 12 撞进 2012 或 12.5。
    """
    nums = data_numbers(text)
    if len(nums) < 2:
        return False
    src = norm_source(source)
    hits = []
    for n in nums:
        pos = [m.start() for m in re.finditer(r'(?<![\d.])%s(?!\.?\d)' % re.escape(n), src)]
        if not pos:
            return False
        hits.append(pos)
    return any(all(any(abs(q - p) <= window for q in other) for other in hits[1:]) for p in hits[0])
