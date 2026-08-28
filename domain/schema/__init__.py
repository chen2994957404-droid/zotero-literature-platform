# -*- coding: utf-8 -*-
"""schema · 结构化抽取的字段定义与文本处理（纯逻辑，公理）

**这一块回答的是「要抽什么、怎么问、抽完怎么摆成表」**，
不回答「从哪读文件、调哪个模型、写到哪去」—— 那些是编排环 `pipelines/extract` 的事。

为什么单独成块（架构宪法·首要判据）：
    字段 schema 是**我们自己的领域知识**，十年不变的那一类；
    而模型、API、目录布局几个月就换一次。混在一个脚本里，
    换模型要动 schema、加字段要动 I/O，谁都不敢改。

**加字段的规矩**：改 `SCHEMA` 的同时把 `SCHEMA_VER` +1。
版本号会随每条记录进状态库，于是「哪些文献缺这个新字段」变成一句
`jobs.stale('extract', schema_ver=N)` —— 不用翻文件、也不用人肉记得改过什么。

对外接口：
  - SCHEMA / SCHEMA_VER      : 字段定义与版本
  - build_user_prompt        : 抽取提示词
  - build_eval_prompt        : 自检提示词（对照原文查漏抽/幻觉）
  - hierarchical_body        : 层次化取正文（优于固定截断）
  - si_body                  : 层次化取 SI（合成配方就在这儿）
  - is_review                : 这篇是不是综述（决定进哪张表）
  - has_value / coverage     : 「这格有真值吗」「各档次各字段的有值率」
  - tier_label               : 这条记录是哪个档次抽的（精+SI / 精层 / 粗层）
  - parse_property(ies)      : 'tensile strength: 12 MPa' → 可比大小的数
  - compare_table / reviews_table : 记录 → Markdown 表（**返回字符串，不写盘**）
"""
import json
import re

# ── Domain schema: soft matter / dynamic-bond elastomers / self-healing ──
# Each field description goes into the prompt to guide extraction. Change domain = change here.
# 输出全英文（原生，给 LLM/机器用；只有精读/问答给人看的才中文）。
SCHEMA = {
    "material_system":     "Core material system (e.g. polyborosiloxane PBS, PDMS-based elastomer, dynamic phase-locked adhesive), one sentence",
    "dynamic_bond_type":   "Interaction providing reversible/dynamic crosslinking (hydrogen bond, boroxine B-O-B, metal coordination, phase-separated nanodomains, etc.)",
    "precursors":          "Main precursors/raw materials and ratio (e.g. PDMS:boric acid = 10:1)",
    "synthesis_conditions":"Key synthesis/processing conditions, always with numbers (temperature, time, atmosphere, etc.)",
    "characterization":    "List of main characterization methods (e.g. GPC, FTIR, rheology, SAXS)",
    "key_properties":      "Any quantitative results — not only mechanical; covers mechanical (tensile strength/toughness/modulus), molecular weight (Mn/Mw/PDI), rheology/viscosity, thermal stability, conductivity/ionic conductivity, sensing sensitivity, self-healing efficiency, etc. Write each as 'property: value+unit' (e.g. 'tensile strength: 12 MPa', 'Mn: 3.2×10^4 g/mol', 'complex viscosity: 1.5×10^3 Pa·s', 'ionic conductivity: 8.2×10^-5 S/cm'). Extract whenever the text reports a quantitative result with unit; only use N/A if none",
    "self_healing":        "Whether it has self-healing/reversibility and its mechanism in one sentence; N/A if none",
    "structure_property":  "The structure-property causal relationship stated in the paper (what structural feature causes what property change)",
    "key_finding":         "The single most important finding/innovation, one sentence",
    "limitation":          "Limitation or open problem the paper states itself; N/A if none",
    "doc_type":            "Document type: 'research' for research articles; 'review' for reviews/surveys/perspectives. Reviews should not force single-system numeric fields.",
}

# 改了 SCHEMA 就 +1。见本文件开头「加字段的规矩」。
SCHEMA_VER = 1

SYS = (
    "You are a materials-science literature structured-extraction engine. Extract information "
    "only from the given text; never fabricate or extrapolate. Fill any field you cannot find "
    "with \"N/A\". Always extract numbers together with their units, keep the original significant "
    "figures, do not convert. Output exactly one JSON object, no explanation, no markdown code fences. "
    "All values in English (native, machine-readable)."
)

EVAL_SYS = (
    "You are a strict extraction QA checker. Given the source text, an extraction schema, "
    "and an extracted JSON, check two things: (1) MISSED — fields marked N/A but whose data "
    "actually appears in the source; (2) HALLUCINATED — values in the JSON that cannot be found "
    "in the source. Output one JSON: {\"ok\": true/false, \"missed\": [\"field: what was missed\"], "
    "\"hallucinated\": [\"field: the value not in source\"]}. If clean, ok=true and empty lists. "
    "No explanation, no code fences."
)


def _field_list():
    return "\n".join(f'  - "{k}": {v}' for k, v in SCHEMA.items())


def build_user_prompt(title, body, si=''):
    """抽取提示词；`si` 是补充材料全文（可空）。

    **为什么要带 SI**：正文只写结论，「投料量、配比、温度、时间」几乎全在 SI 里。
    不给 SI 时 `synthesis_conditions` 的有值率只有 36%（2026-08-28 实测 39 篇精层）。
    """
    p = (
        f"Paper title: {title}\n\n"
        f"Extract the following fields as JSON (keys are the English field names, values in English, keep original units):\n"
        f"{_field_list()}\n\n"
        f"===== MAIN TEXT START =====\n{body}\n===== MAIN TEXT END ====="
    )
    if si and si.strip():
        p += (
            f"\n\n===== SUPPLEMENTARY INFORMATION START =====\n{si}\n"
            "===== SUPPLEMENTARY INFORMATION END =====\n\n"
            "The supplementary information belongs to this same paper and usually contains the "
            "exact experimental recipe (amounts, weight/molar ratios, concentrations, temperature, "
            "time, atmosphere). Prefer those numbers for \"precursors\" and \"synthesis_conditions\"."
        )
    return p


def build_eval_prompt(data, body):
    """自检：对照原文查「该抽没抽」和「抽了原文里没有的」。"""
    return (f"Schema:\n{_field_list()}\n\n"
            f"Extracted JSON:\n{json.dumps(data, ensure_ascii=False)}\n\n"
            f"===== SOURCE TEXT =====\n{body}\n===== END =====")


def build_feedback(report):
    """把自检结果变成「重抽时该注意什么」的一段话。"""
    return (f"Your previous extraction had issues. MISSED: {report.get('missed')}. "
            f"HALLUCINATED (remove or fix these): {report.get('hallucinated')}. "
            f"Re-extract correctly.")


# ── 正文预处理 ────────────────────────────────────────────────────────
def strip_refs(md):
    """去掉参考文献之后的部分（与向量化线同一思路）。

    切完若剩不到原文两成，说明多半是误判（比如正文里就出现了 "References" 这个词），
    宁可不切 —— 切错的代价是整篇抽不出东西。
    """
    pat = re.compile(r'(?im)^\s*#{0,4}\s*(references|reference|bibliography|参考文献|literature\s+cited)\s*$')
    m = pat.search(md)
    cut = m.start() if m else len(md)
    body = md[:cut].strip()
    return body if len(body) > len(md) * 0.2 else md


def hierarchical_body(md, budget=14000):
    """层次化取正文（优于固定截断）：去参考文献、去图片标记，若仍超预算，
    优先保留 摘要+引言+实验/方法+结论 这些高信息密度章节。

    为什么不直接截断：固定截断会把结论和机理讨论整段切掉 ——
    而那正是抽取最需要的部分（精读线上也栽过同一个跟头）。
    """
    md = strip_refs(md)
    md = re.sub(r'!\[\]\(images/[^)]+\)', '', md)          # 去图片
    if len(md) <= budget:
        return md
    priority = re.compile(r'(?i)(abstract|introduction|experiment|method|result|discussion|conclusion|摘要|引言|实验|方法|结果|结论)')
    blocks = re.split(r'(?m)^(#{1,3}\s.*)$', md)
    kept, used = [md[:1500]], 1500                          # 开头（含摘要）一定保留
    for i in range(1, len(blocks) - 1, 2):
        head, content = blocks[i], blocks[i + 1]
        seg = head + content
        if priority.search(head) and used + len(seg) < budget:
            kept.append(seg)
            used += len(seg)
    return "\n".join(kept)


_SI_PRIORITY = re.compile(
    r'(?i)(material|synthes|preparation|sample prep|experiment|method|procedure|protocol'
    r'|characteri|measurement|instrument|材料|合成|制备|实验|方法|表征|测试)')

# 配方线索：带单位的数字与配比 —— 「这一节像不像在讲怎么配料」的粗判据
_RECIPE_CUE = re.compile(
    r'(?i)(\d+\s*(mmol|mol|mg|kg|ml|wt\s*%|vol\s*%|w/w|°\s*c|℃|rpm|min|hour|hr)\b'
    r'|\bratio\b|\d+\s*:\s*\d+|投料|配比|质量比|摩尔比)')


def _recipe_score(text):
    """这一段里有多少配方线索。越多越像「怎么配出来的」，越该喂给模型。"""
    return len(_RECIPE_CUE.findall(text))


def si_body(md, budget=8000):
    """层次化取 SI：先要「材料 / 合成 / 制备 / 实验方法」章节，
    还有余量就按**配方线索密度**（投料量、配比、温度、时间这些数字）补。

    与 `hierarchical_body` 的区别：SI 没有摘要，开头往往是目录或图注，
    所以不保留开头；而且很多 SI 根本没有「Materials」小标题，
    配方数字散在各节的图注里（实测 IDY9U372 就是这样）—— 只按标题挑会漏掉，
    所以第二轮按线索密度排序补足。
    """
    md = strip_refs(md)
    md = re.sub(r'!\[\]\(images/[^)]+\)', '', md).strip()      # 去图片
    if len(md) <= budget:
        return md
    blocks = re.split(r'(?m)^(#{1,4}\s.*)$', md)
    if len(blocks) < 3:
        return md[:budget]                                       # 没有章节标题：只能截断
    secs = [(i, blocks[i] + blocks[i + 1]) for i in range(1, len(blocks) - 1, 2)]
    kept, used = {}, 0
    for idx, seg in secs:                                        # 第一轮：优先章节
        if _SI_PRIORITY.search(blocks[idx]) and used + len(seg) <= budget:
            kept[idx] = seg
            used += len(seg)
    for idx, seg in sorted(secs, key=lambda x: -_recipe_score(x[1])):   # 第二轮：配方线索多的
        if idx in kept or _recipe_score(seg) == 0 or used + len(seg) > budget:
            continue
        kept[idx] = seg
        used += len(seg)
    if not kept:
        return md[:budget]
    return "\n".join(kept[i] for i in sorted(kept))              # 按原文顺序输出


# ── 分流与出表 ────────────────────────────────────────────────────────
_REVIEW_WORDS = ('review', 'overview', 'recent advances', 'recent progress',
                 'a survey', 'perspective', '综述', '研究进展', '进展')


def is_review(record):
    """这篇是不是综述：优先信模型给的 doc_type，兜底看标题特征词。

    为什么要分流：综述没有单一体系的数值，硬塞进数值对比表只会污染它 ——
    对比表的价值全在「竖着比同一字段」，多一行 N/A 就少一分可比性。
    """
    if 'review' in str(record.get('doc_type', '')).lower():
        return True
    t = (record.get('title') or '').lower()
    return any(w in t for w in _REVIEW_WORDS)


COMPARE_COLS = ['material_system', 'dynamic_bond_type', 'synthesis_conditions',
                'key_properties', 'self_healing', 'key_finding']


# ── 来源档次：这条记录是拿什么料抽出来的 ──────────────────────────────
# 为什么必须标出来（2026-08-28）：粗层是拿 Zotero 全文索引 + 本地小模型抽的，
# 空格多得多。两档混在一张表里且看不出区别，用户竖着比字段时
# **分不清空白是「这篇本来就没有」还是「粗层没抽到」** —— 对比表的价值就废了。
SOURCE_FINE = 'fine'        # MineRU 全文 + 云端大模型
SOURCE_LOCAL = 'local'      # MineRU 全文 + **本地** 模型（料一样好，模型小一档）
SOURCE_COARSE = 'coarse'    # Zotero 全文索引 + 本地小模型（数据抽取/extract_library.py）

TIER_FINE_SI = '精+SI'
TIER_FINE = '精层'
TIER_LOCAL_SI = '本地+SI'
TIER_LOCAL = '本地'
TIER_COARSE = '粗层'
TIER_ORDER = [TIER_FINE_SI, TIER_FINE, TIER_LOCAL_SI, TIER_LOCAL, TIER_COARSE]


def tier_label(record):
    """这条记录属于哪一档。老记录没有 `source` 字段 → 一律算精层（粗层从来都带标记）。

    **料和模型是两件事**：`本地+SI` 的料和 `精+SI` 一样好（MineRU 全文 + SI），
    差的只是模型档次。分开标，才知道「这一格该不该花钱升级」。
    """
    src = str(record.get('source') or SOURCE_FINE).lower()
    if src == SOURCE_COARSE:
        return TIER_COARSE
    if src == SOURCE_LOCAL:
        return TIER_LOCAL_SI if record.get('si_used') else TIER_LOCAL
    return TIER_FINE_SI if record.get('si_used') else TIER_FINE


# 「没有值」的各种写法。模型不总是老老实实写 N/A。
EMPTY_VALUES = {'', 'n/a', 'na', 'none', 'null', '-', 'not available', 'not specified',
                'not reported', 'not mentioned', 'unknown', '无', '未提及', '未知'}


def has_value(v):
    """这格是真有内容，还是等于空？—— 有值率统计与后续入库的唯一判据。"""
    if v is None:
        return False
    if isinstance(v, (list, tuple, set)):
        return any(has_value(x) for x in v)
    if isinstance(v, dict):
        return any(has_value(x) for x in v.values())
    return str(v).strip().lower() not in EMPTY_VALUES


def coverage(records, cols=None):
    """各档次 × 各字段的有值率：{档次: {'n': 篇数, 'rate': {字段: 0~1}}}。

    这是「数据有多准」的体温计：粗层 synthesis_conditions 只有 5%，
    这类事实必须摆在表里，不能只活在某次对话里。
    """
    cols = cols or list(SCHEMA.keys())
    out = {}
    for r in records:
        t = out.setdefault(tier_label(r), {'n': 0, 'hit': {c: 0 for c in cols}})
        t['n'] += 1
        for c in cols:
            if has_value(r.get(c)):
                t['hit'][c] += 1
    return {k: {'n': v['n'],
                'rate': {c: (v['hit'][c] / v['n'] if v['n'] else 0.0) for c in cols}}
            for k, v in out.items()}


def coverage_table(records, cols=None):
    """有值率小表（Markdown 字符串），贴在对比表开头当「本表可信度说明」。"""
    cols = cols or COMPARE_COLS
    cov = coverage(records, cols)
    if not cov:
        return ''
    tiers = [t for t in TIER_ORDER if t in cov] + [t for t in cov if t not in TIER_ORDER]
    rows = ['| 字段 | ' + ' | '.join(f'{t}({cov[t]["n"]}篇)' for t in tiers) + ' |',
            '|' + '---|' * (len(tiers) + 1)]
    for c in cols:
        rows.append('| ' + c + ' | '
                    + ' | '.join(f'{round(cov[t]["rate"][c] * 100)}%' for t in tiers) + ' |')
    return '\n'.join(rows)


def compare_table(records):
    """研究论文的横向对比表（Markdown 字符串）。**不写盘** —— 写哪去是编排环的事。"""
    research = [r for r in records if not is_review(r)]
    reviews = [r for r in records if is_review(r)]
    # 按档次排序：精+SI → 精层 → 粗层。同档保持原顺序（按 key），
    # 这样「可信的那几十行」聚在一起，竖着比才有意义。
    rank = {t: i for i, t in enumerate(TIER_ORDER)}
    research = sorted(research, key=lambda r: rank.get(tier_label(r), 99))
    rows = ["# 结构化抽取 · 横向对比表（仅研究论文）", "",
            "> 自动生成。竖着比同一字段，找矛盾、空白、规律。",
            f"> 研究论文 {len(research)} 篇；综述 {len(reviews)} 篇已分流到 compare_reviews.md"
            f"（综述无单一体系数值，不入本表）。", "",
            "> **先看「来源」列再看格子**：`精+SI` = MineRU 全文+SI+云端大模型，最全；"
            "`精层` = 只读了正文，合成条件多半缺；"
            "`本地+SI` = 料一样全，但用本地模型抽的（免费，准确度低一档）；"
            "`粗层` = Zotero 全文索引+本地小模型，空格多是**没抽到**，不是原文没有。", "",
            "各档次的字段有值率（空格到底是「没有」还是「没抽到」，看这里）：", ""]
    cov = coverage_table(research)
    if cov:
        rows += [cov, ""]
    header = ['论文', '来源'] + COMPARE_COLS
    rows.append('| ' + ' | '.join(header) + ' |')
    rows.append('|' + '---|' * len(header))
    for r in research:
        cells = [str(r.get('title', ''))[:30], tier_label(r)] + [
            str(r.get(c, 'N/A')).replace('\n', ' ')[:80] for c in COMPARE_COLS]
        rows.append('| ' + ' | '.join(cells) + ' |')
    return '\n'.join(rows)


def reviews_table(records):
    """综述清单（Markdown 字符串）；没有综述则返回 None。"""
    reviews = [r for r in records if is_review(r)]
    if not reviews:
        return None
    rows = ["# 综述清单（从对比表分流）", "",
            "> 这些是综述/进展类文献，不套研究论文的数值 schema。"
            "适合了解领域全景、进问答库。", "",
            "| 论文 | 核心发现 | 局限 |", "|---|---|---|"]
    for r in reviews:
        rows.append('| ' + ' | '.join([
            str(r.get('title', ''))[:40],
            str(r.get('key_finding', 'N/A')).replace('\n', ' ')[:90],
            str(r.get('limitation', 'N/A')).replace('\n', ' ')[:60]]) + ' |')
    return '\n'.join(rows)



# ── 性能数值：字符串 → 能比大小的数 ────────────────────────────────────
# 为什么要这一步（2026-08-28，数据库方向③）：
#     key_properties 里存的是 'tensile strength: 12 MPa' 这种人话。
#     人能看，机器比不了大小 —— 「拉伸强度 > 10 MPa 的都有哪些」这类问题
#     只要还停在字符串上就永远答不了。把它拆成 (名字, 数, 单位) 才能进查询库。
# **不做单位换算**：MPa 与 kPa 混在一起时宁可让人看见，也不偷偷换算错。
# 查询时按名字 + 单位一起筛（见 pipelines/paper_db）。

_NUM = (r'([-+]?\d+(?:[.,]\d+)?)'                    # 3.2
        r'(?:\s*[eE]([-+]?\d+)'                      # 3.2e-5
        r'|\s*[×xX*]\s*10\s*\^?\s*([-+]?\d+)'      # 3.2 × 10^4
        r'|\s*[×xX*]\s*10\s*([-+−]\d+))?')           # 3.2 × 10-5（上标丢了的情形）
_CMP = r'([~≈><≥≤]|about|approx\.?|up to|over|more than|less than)?\s*'
_PROP_RE = re.compile(r'(?i)^\s*' + _CMP + _NUM)
_RANGE_RE = re.compile(_NUM + r'\s*[–—\-~]\s*' + _NUM)

_CMP_MAP = {'~': '~', '≈': '~', 'about': '~', 'approx': '~', 'approx.': '~',
            '>': '>', 'over': '>', 'more than': '>', 'up to': '<',
            '<': '<', 'less than': '<', '≥': '>', '≤': '<'}


def _to_float(m, base=1):
    """把匹配到的「数 + 指数」拼成一个 float；拼不出来返回 None。"""
    try:
        v = float(str(m.group(base)).replace(',', ''))
    except (TypeError, ValueError):
        return None
    for g in (base + 1, base + 2, base + 3):
        exp = m.group(g)
        if exp:
            try:
                v *= 10 ** int(str(exp).replace('−', '-'))
            except ValueError:
                return None
            break
    return v


def parse_property(text):
    """`'tensile strength: 12 MPa'` → `{'name','value','unit','cmp','value_max','raw'}`。

    拆不出数字时 value 为 None（`'self-healing: yes'` 这种照样保留，
    只是不能参与大小比较）。**不换算单位**，unit 原样留着。
    """
    raw = str(text).strip()
    name, _, rest = raw.partition(':')
    if not rest:                       # 没有冒号：整句当名字，试着从里面找数
        name, rest = raw, raw
    name = name.strip().lower()
    rest = rest.strip()
    out = {'name': name, 'value': None, 'value_max': None,
           'unit': '', 'cmp': '', 'raw': raw}

    rng = _RANGE_RE.search(rest)
    m = _PROP_RE.match(rest)
    if rng and (not m or rng.start() <= m.start(2)):
        out['value'] = _to_float(rng, 1)
        out['value_max'] = _to_float(rng, 5)
        tail = rest[rng.end():]
    elif m:
        c = (m.group(1) or '').strip().lower()
        out['cmp'] = _CMP_MAP.get(c, '')
        out['value'] = _to_float(m, 2)
        tail = rest[m.end():]
    else:
        return out
    out['unit'] = tail.strip().strip('.,;').strip()[:24]
    return out


def parse_properties(record):
    """一条记录的 key_properties → 解析过的数值列表（拆不出数的也留着）。"""
    v = record.get('key_properties')
    if not v:
        return []
    items = v if isinstance(v, (list, tuple)) else re.split(r'[;\n]| \| ', str(v))
    return [parse_property(x) for x in items if str(x).strip()]


# ── 抽出来的数字，原文里找得到吗 ──────────────────────────────────────
# 「哪个模型更靠谱」不能靠读着顺不顺。最容易自动化、也最要命的一条是：
# **它给的数字是不是编的**。把输出里的数字逐个回原文找，找不到的挑出来看。
_NUM_TOKEN = re.compile(r'\d+(?:\.\d+)?')


def number_grounding(data, source):
    """抽取结果里的数字，有多少能在原文里逐字找到。返回 (命中, 总数, 没找到的列表)。

    **这是粗判据，不是判决**：单位换算（1.5×10^4 vs 15000）、
    模型把 90% 写成 0.9，都会算成「没找到」。所以要看的是**两个模型的相对差距**，
    以及没找到的那些具体是什么 —— 一眼就能看出是换算还是瞎编。
    只数两位及以上的数字：个位数（1、2、3）在任何长文里都必然命中，没有区分度。
    """
    src = re.sub(r'[\s,]', '', str(source))
    miss, hit, total = [], 0, 0
    for k, v in (data or {}).items():
        text = '; '.join(str(x) for x in v) if isinstance(v, (list, tuple)) else str(v)
        for tok in _NUM_TOKEN.findall(text):
            if len(tok.replace('.', '')) < 2:
                continue
            total += 1
            if tok in src:
                hit += 1
            else:
                miss.append(f'{k}: {tok}')
    return hit, total, miss


def make_record(key, title, doi, data, schema_ver=None,
                source=SOURCE_FINE, si_used=False):
    """抽取结果 → 落盘用的记录。

    **带上版本号**，否则以后没法知道它是哪版 schema 抽的；
    **带上来源档次与是否读了 SI**，否则以后没法知道一个空格是
    「原文没有」还是「料不够没抽到」（这正是 2026-08-28 对比表的病）。
    """
    return {'key': key, 'title': title, 'doi': doi or '',
            'schema_ver': SCHEMA_VER if schema_ver is None else schema_ver,
            'source': source, 'si_used': bool(si_used), **data}
