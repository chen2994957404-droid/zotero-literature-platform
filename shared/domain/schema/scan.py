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

from . import parse_property, normalize_property_name, PROPERTY_ALIASES

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


# ── 表格：脚本最该干、模型最容易读错的地方 ────────────────────────────
# MineRU 解析出来的表是 **HTML**（`<table><tr><td>`，实测 42 篇里 18 篇有），
# 不是 markdown 管道表。一张表里四样东西同时在场：
#   行首 = 样品名 · 表头 = 性能名与单位 · 交叉点 = 数值 · 表前一句 = 标题（出处）
# 模型读这种表最容易串行串列（尤其带 colspan/rowspan 的双层表头），
# 而脚本只是按坐标取值，**串不了**。
import html as _html
from html.parser import HTMLParser as _HTMLParser

# ── 洗表格：三种脏，顺序不能换 ────────────────────────────────────────
# **先洗 LaTeX，再判转置** —— 2026-09-07 实测踩到：转置表的第一列写的是
# `$T_g$ by max $G''$`、`$d_w$ (μm)`，明明是性能名，但词表认不出带 `$` 的名字，
# 于是「有没有转置表」这个问题被答成了「没有」。洗完再问，答案就变了。
_BS = chr(92)
_BS_RE = re.escape(_BS)

_GREEK = {
    'Delta': 'Δ', 'alpha': 'α', 'beta': 'β', 'gamma': 'γ', 'delta': 'δ',
    'epsilon': 'ε', 'zeta': 'ζ', 'eta': 'η', 'theta': 'θ', 'kappa': 'κ',
    'lambda': 'λ', 'mu': 'μ', 'nu': 'ν', 'pi': 'π', 'rho': 'ρ',
    'sigma': 'σ', 'tau': 'τ', 'phi': 'φ', 'chi': 'χ', 'psi': 'ψ',
    'omega': 'ω', 'Omega': 'Ω', 'Sigma': 'Σ', 'Phi': 'Φ',
    'times': '×', 'cdot': '·', 'pm': '±', 'approx': '≈',
    'leq': '≤', 'geq': '≥', 'circ': '°', 'degree': '°',
}
# 只起排版作用、洗掉不影响含义的命令
_TEXT_CMD = re.compile(_BS_RE + r'(?:text|mathrm|mathit|mathbf|rm|overline|bar|hat|vec)\s*')
_CMD = re.compile(_BS_RE + r'([A-Za-z]+)')
_SUBSUP = re.compile(r'[_^]\s*\{([^{}]*)\}')
# 排版用的空格命令（`\;` `\,` `\!` `\:`）—— 不去掉会在正文里留下裸分号
_SPACE_CMD = re.compile(_BS_RE + r'[;,:!> ]')
# `10^{-10}` / `10 ^ -10` 里的幂次：**这个 `^` 必须留住**
_EXP_RE = re.compile(r'(?<=\d)\s*\^\s*\{?\s*([-+−]?\d+)\s*\}?')
# 光杆的 `10^-10`（前面没有「A ×」）
_BARE_POW_RE = re.compile(r'(?<![\d.×xX*])\s*\b10\^([-+]?\d+)')


def clean_label(text):
    r"""表头 / 样品名里的 LaTeX → 人和词表都认得的写法。

    `$\Delta H_c$` → `ΔHc`；`$\overline{M}_{n}$` → `Mn`；
    `$k_{hn} \times 10^{-3}$` → `khn × 10-3`。

    **为什么值得单独一个函数**：42 篇实测里 150/428 条测量的名字带 LaTeX，
    38 条样品名带 LaTeX。不洗，这些名字既归一不了、也认不出是不是性能名 ——
    后面那个「这张表是不是转置的」的判断就会直接答错。
    """
    t = str(text or '')
    if not t:
        return ''
    t = t.replace('$', ' ')
    t = _TEXT_CMD.sub(' ', t)
    t = _SUBSUP.sub(lambda m: m.group(1), t)            # _{n} → n，^{-3} → -3
    t = re.sub(r'[_^]\s*([A-Za-z0-9+-])', lambda m: m.group(1), t)
    t = _CMD.sub(lambda m: _GREEK.get(m.group(1), ' '), t)
    t = t.replace('{', '').replace('}', '').replace(_BS, ' ')
    return re.sub(r'\s+', ' ', t).strip()


def clean_body(md):
    r"""**整段正文**里的 LaTeX → 数字探测器和模型都读得懂的写法。保留换行与表格行。

    `clean_label` 的正文版。为什么必须有它（2026-09-08 实测，踩坑 #143）：
    `clean_label` 是为表头写的，正文这条线从来没洗过 LaTeX，于是
    `$10^{-10}\;\mathrm{M}$`、`$9.8 \pm 0.3$ MPa` 这些**根本没被认成数字**——
    `split_chunks` 的「这段有没有 ≥2 个数」筛子把整段判成「没数字」直接丢掉，
    模型连看都没看见。实测：P2Q5TYFR 只有 38% 的正文被喂进去，CL2HILJ9 只有 52%。

    与 `clean_label` 的唯一区别：**不塌换行**（塌了 markdown 的段落与表格就没了），
    只压同一行内的连续空格。
    """
    t = str(md or '')
    if not t:
        return ''
    t = t.replace('$', ' ')
    t = _SPACE_CMD.sub(' ', t)            # \; \, \! 这类排版空格，先去掉反斜杠
    t = _TEXT_CMD.sub(' ', t)
    # **指数要留住 `^`**：`10^{-10}` 塌成 `10-10` 就变成了一个「区间」，
    # 数字探测器和人都会读错。先把幂次单独接出来，再让下面的规则去处理下标。
    t = _EXP_RE.sub(lambda m: '^' + m.group(1).replace('−', '-'), t)
    t = _SUBSUP.sub(lambda m: m.group(1), t)
    # 只塌下标与「字母上标」；**数字上标（幂次）刚保住，别在这里又吃掉**
    t = re.sub(r'_\s*([A-Za-z0-9+-])', lambda m: m.group(1), t)
    t = re.sub(r'\^\s*([A-Za-z])', lambda m: m.group(1), t)
    t = _CMD.sub(lambda m: _GREEK.get(m.group(1), ' '), t)
    t = t.replace('{', '').replace('}', '').replace(_BS, ' ')
    # 光杆的 `10^-10` 补成 `1×10^-10` —— 数值正则认得后者，认不得前者。
    t = _BARE_POW_RE.sub(
        lambda m: (' ' if m.group(0)[:1].isspace() else '')
        + '1' + chr(215) + '10^' + m.group(1), t)
    # 千分位空格：`40 000 g/mol` 不并起来会被读成 40（实测漏过一条金标）
    # 误差棒剥掉：`9.8 ± 0.3 MPa` 不剥会被读成 0.3（±0.3 才是被当成值的那个）
    t = re.sub(r'\s*[±]\s*\d+(?:\.\d+)?', '', t)
    t = re.sub(r'(?<=\d)[  ](?=\d{3}(?!\d))', '', t)
    return re.sub(r'[ 	]+', ' ', t)


def _known_property(name):
    """这个名字是不是词表认得的性能？（**洗过再问**，见上面那段。）"""
    n = clean_label(name)
    if not n:
        return False
    return normalize_property_name(n) in PROPERTY_ALIASES


def _looks_property(name):
    """比词表宽一点的判断：**名字后面挂着括号单位**，那就是个性能名。

    只靠词表不够 —— 2026-09-07 实测，转置表的第一列写着
    `dw (μm)`、`apparent Ea (kJ/mol)`、`onset temperature of flow (°C)`，
    词表一个都不认得，于是那几张表没被转回来，样品与性能一直是对调的。
    **样品名几乎不会带括号单位**，所以这个信号很干净。
    """
    n = clean_label(name)
    if not n or re.fullmatch(r'[-+±\d.,%\s]+', n):
        return False
    if _known_property(n):
        return True
    m = _HEAD_UNIT_RE.search(n)
    return bool(m and _clean_unit(m.group('unit')))


# 投料量的单位。**不含裸 `%`** —— 自修复效率也是 %，那是性能不是配方。
_COMPOSITION_UNITS = ('wt%', 'wt.%', 'wt %', 'vol%', 'vol.%', 'mol%', 'mol.%',
                      'phr', '份')
_NUMLIKE_RE = re.compile(r'\d+(?:\.\d+)?')
_ERRBAR_RE = re.compile(r'[（(]\s*±[^)）]*[)）]|±\s*\d+(?:\.\d+)?')
_SCI_RE = re.compile(r'(?:[eE]|[×xX]\s*10)')
_RANGE_CELL_RE = re.compile(r'^[-+]?\d+(?:\.\d+)?\s*[–—~-]\s*[-+]?\d+(?:\.\d+)?$')


def _clean_unit(unit):
    """表头括号里抓到的「单位」未必是单位 —— 误差棒和比号也长这样。

    2026-09-07 实测抓到过 `± 1.7`、`±0.03`、`:1` 被当成单位。
    **一个数字挂上假单位，比没有单位更坏**：它会被当真去跟别人比大小。
    """
    t = clean_label(unit)
    if not t or '±' in t:
        return ''
    if re.fullmatch(r'[\d\s.,:;+–—/-]+', t):           # 纯数字、`:1` 这类
        return ''
    return t[:24]


def clean_value_text(text):
    """`12.4 ± 0.3 MPa` → `12.4 MPa`。**误差棒不是第二个数，更不是单位。**

    不剥掉的话 `parse_property` 会把 `± 0.3 MPa` 整个当成单位存进库
    （2026-09-07 实测：正文抽出来的 `19.5 ± 0.2 MPa`，单位那栏就是 `± 0.2 MPa`）。
    一个数字挂上假单位，比没有单位更坏 —— 它会被当真去跟别人比大小。
    """
    t = clean_label(text)
    if not t:
        return ''
    return re.sub(r'\s+', ' ', _ERRBAR_RE.sub(' ', t)).strip()


def _cell_number(cell):
    """一格 → 可解析的那个数；**一格多值就返回 None（不猜）**。

    `PD 1.68 1.28` 这种一格塞两代样品的，硬拆就是往库里灌假数。
    误差棒 `12.4 (±0.10)` 先剥掉再判 —— 那是同一个数的精度，不是第二个数。
    """
    t = clean_value_text(cell)
    if not t:
        return None
    if _RANGE_CELL_RE.match(t) or _SCI_RE.search(t):
        return t                                       # 区间、科学计数法交给 parse_property
    if len(_NUMLIKE_RE.findall(t)) >= 2:
        return None
    return t


_DECIMAL_RE = re.compile(r'\d+\.\d+')


def _is_collapsed(label):
    """整行塌进一个格子的表头（`CFRP Laminate 8.31 13.74`）→ 整列不要。

    MineRU 偶尔把单列表解析成「表头里含着数据」。这种列取出来的每个数
    都挂在错的名字上，**而且不会报错**。

    判据不能是「名字里有两个数」—— 2026-09-07 实测那样会误伤
    `Weight loss (%) 200/800`、`1st cycle`：那些数字是**测试条件**，不是数据。
    塌进来的数据长得不一样：**带小数点**（8.31 13.74），或者密集到四个以上。
    """
    t = clean_label(label)
    return len(_DECIMAL_RE.findall(t)) >= 2 or len(_NUMLIKE_RE.findall(t)) >= 4


def _transpose(grid, head_rows):
    """这张表是不是「第一列是性能、表头是样品」？是就转置回来，不是就返回 None。

    判据：数据行的第一列里，**过半**能被词表认出是性能名（且至少 2 个）。
    认不出就不动 —— 猜错的代价是整张表的样品与性能对调。
    """
    col0 = [(l[0] or '').strip() for l in grid[head_rows:] if l and (l[0] or '').strip()]
    if len(col0) < 2:
        return None
    hit = sum(1 for c in col0 if _looks_property(c))
    if hit < 2 or hit < len(col0) * 0.5:
        return None
    width = max(len(l) for l in grid)
    padded = [list(l) + [''] * (width - len(l)) for l in grid]
    return [list(row) for row in zip(*padded)]


_TABLE_RE = re.compile(r'(?is)<table\b.*?</table>')
# 表头里的单位：`Modulus (MPa)` / `Tensile strength at 250% (MPa)`
# 单位可能在标签中间：双层表头拼起来是 `Modulus (MPa) 1st cycle`。
# 只认结尾的话，这一列的单位就丢了 —— 丢了不报错，只是数字从此没有量纲。
_HEAD_UNIT_RE = re.compile(r'[（(]\s*(?P<unit>[^)）]{1,16})\s*[)）]')


class _TableParser(_HTMLParser):
    """把 `<table>` 拆成二维格子，**展开 colspan / rowspan**。

    不展开的后果是双层表头下的列全部错位 —— 而错位不会报错，
    只会让 12.4 MPa 变成另一个性能的值。宁可代码多十行。
    """

    def __init__(self):
        _HTMLParser.__init__(self)
        self.rows, self._row, self._cell, self._span = [], None, None, {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'tr':
            self._row = []
        elif tag in ('td', 'th') and self._row is not None:
            self._cell = []
            self._span = {'c': int(a.get('colspan') or 1),
                          'r': int(a.get('rowspan') or 1)}

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self._cell is not None:
            text = _html.unescape(''.join(self._cell)).strip()
            self._row.append({'text': text, **self._span})
            self._cell = None
        elif tag == 'tr' and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _grid(rows):
    """带 span 的行 → 规整二维数组（每格都填上真实文本）。"""
    grid, pending = [], {}
    for r in rows:
        line, col = [], 0
        for cell in r:
            while col in pending and pending[col][1] > 0:
                line.append(pending[col][0])
                pending[col] = (pending[col][0], pending[col][1] - 1)
                col += 1
            for _ in range(cell['c']):
                line.append(cell['text'])
                if cell['r'] > 1:
                    pending[col] = (cell['text'], cell['r'] - 1)
                col += 1
        while col in pending and pending[col][1] > 0:
            line.append(pending[col][0])
            pending[col] = (pending[col][0], pending[col][1] - 1)
            col += 1
        grid.append(line)
    return grid


def _is_headerish(line):
    """这一行像表头吗：格子里基本没有纯数字。"""
    vals = [c for c in line if c.strip()]
    if not vals:
        return False
    numeric = sum(1 for c in vals if re.fullmatch(r'[-+±\d.,%\s]+', c))
    return numeric <= len(vals) * 0.3


def _columns(grid):
    """表头（可能两层）→ 每列的 (性能名, 单位)。返回 (列定义, 数据起始行号)。

    名字与单位都**洗过**：LaTeX 化掉，误差棒不当单位（见 `clean_label` / `_clean_unit`）。
    """
    head_rows = 0
    for line in grid[:3]:
        if _is_headerish(line):
            head_rows += 1
        else:
            break
    head_rows = max(head_rows, 1)
    width = max(len(l) for l in grid)
    cols = []
    for i in range(width):
        parts, seen = [], set()
        for r in range(head_rows):
            if i < len(grid[r]):
                t = clean_label(grid[r][i])
                if t and t not in seen:
                    parts.append(t)
                    seen.add(t)
        label = ' '.join(parts)
        m = _HEAD_UNIT_RE.search(label)
        unit = _clean_unit(m.group('unit')) if m else ''
        if unit:
            name = (label[:m.start()] + ' ' + label[m.end():]).strip()
            cols.append((name or label, unit))
        else:
            cols.append((label, ''))
    return cols, head_rows


def _caption(md, start):
    """表前最近的一句话当标题；顺带找表号（找不到就空 —— 空是事实）。"""
    before = md[max(0, start - 400):start].strip()
    line = [x.strip() for x in before.splitlines() if x.strip()]
    cap = line[-1] if line else ''
    return cap[:160], nearest_ref(md, start)


def _table_rows(grid, cols, head_rows, ref, cap):
    """规整表格 → 测量列表。取不到干净的数就跳过，**一条都不猜**。"""
    out = []
    for line in grid[head_rows:]:
        if not line:
            continue
        sample = clean_label(line[0])
        if not sample or re.fullmatch(r'[-+±\d.,%\s]+', sample):
            continue          # 第一列是数字 → 这张表没有样品列，交给模型
        if re.fullmatch(r'[a-z]', sample):
            continue          # 表末的脚注行（a/b/c），不是样品。元素符号是大写，误伤不到
        for i, cell in enumerate(line[1:], start=1):
            if i >= len(cols):
                break
            name, unit = cols[i]
            if not name or _is_collapsed(name):
                continue
            text = _cell_number(cell)
            if text is None:
                continue
            parsed = parse_property('%s %s' % (text, unit))
            if parsed['value'] is None:
                continue
            kind = ('composition'
                    if unit in _COMPOSITION_UNITS and not _known_property(name)
                    else 'measurement')
            out.append({
                'sample_id': sample, 'name': normalize_property_name(name),
                'raw_name': name,
                'value': parsed['value'], 'value_max': parsed['value_max'],
                'unit': unit or parsed['unit'], 'cmp': parsed['cmp'],
                'condition': '', 'location': ref, 'section': 'main',
                'method': 'script', 'kind': kind,
                'raw': '%s: %s %s' % (name, text, unit),
                'caption': cap})
    return out


def scan_tables(md):
    """全文里的每张表 → 测量列表（**带样品、性能、单位、出处**，全部由脚本得到）。

    `sample_id` 取行首那一格 —— 论文表格的第一列几乎总是样品名。
    遇到「第一列是性能名」的转置表会先转回来（`_transpose`）。
    取不到数的格子直接跳过；表头认不出性能名的列也照样入库，
    只是 `name` 没归一 —— **宁可留着没归一的名字，也别悄悄丢掉一个真数字**。

    每条带 `kind`：`'measurement'` 是性能，`'composition'` 是投料量
    （`PA6 80 wt%` 那种）。投料量属于样品的配方，不该进测量层去跟人比大小。
    """
    out = []
    for m in _TABLE_RE.finditer(md):
        p = _TableParser()
        try:
            p.feed(m.group(0))
        except Exception:
            continue
        if len(p.rows) < 2:
            continue
        grid = _grid(p.rows)
        cols, head_rows = _columns(grid)
        flipped = _transpose(grid, head_rows)
        if flipped is not None:            # 转置表：转回来再按同一套规则读
            grid = flipped
            cols, head_rows = _columns(grid)
        cap, ref = _caption(md, m.start())
        out += _table_rows(grid, cols, head_rows, ref, cap)
    return out
