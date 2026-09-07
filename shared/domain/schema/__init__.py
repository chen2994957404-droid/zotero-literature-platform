# -*- coding: utf-8 -*-
"""schema · 结构化抽取的字段定义与文本处理（纯逻辑，公理）

**这一块回答的是「要抽什么、怎么问、抽完怎么摆成表」**，
不回答「从哪读文件、调哪个模型、写到哪去」—— 那些是编排环 `tools/extract` 的事。

为什么单独成块（架构宪法·首要判据）：
    字段 schema 是**我们自己的领域知识**，十年不变的那一类；
    而模型、API、目录布局几个月就换一次。混在一个脚本里，
    换模型要动 schema、加字段要动 I/O，谁都不敢改。

**加字段的规矩**：改 `SCHEMA` 的同时把 `SCHEMA_VER` +1。
版本号会随每条记录进状态库，于是「哪些文献缺这个新字段」变成一句
`jobs.stale('extract', schema_ver=N)` —— 不用翻文件、也不用人肉记得改过什么。

对外接口：
  - SCHEMA / SCHEMA_VER      : 字段定义与版本
  - build_user_prompt        : 抽取提问（字段清单 + 正文 + SI）
  - build_eval_prompt        : 自检提问（对照原文查漏抽/幻觉）
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
# v2（2026-09-06）：新增样品层与测量层 —— 见下面 SAMPLE_SCHEMA / MEAS_SCHEMA。
SCHEMA_VER = 2


# ── 样品层与测量层（v2）────────────────────────────────────────────────
# **为什么要多这两层**（2026-09-06 重新规划数据库时定的）：
# v1 的最小单元是「一篇论文」，可一篇论文里常有 PBS-1/PBS-2/PBS-3 好几个配方，
# 各有各的强度。全挤进 key_properties 一句话里，拆出来的数字**不知道是哪个样品的**,
# 于是「强度>10 MPa 的体系有哪些」答出来的是论文，不是体系 —— 越大越没法用。
# 而且 v1 的数字没有出处（表几图几、正文还是 SI），写论文时不敢引，还得翻回原文。
#
# 三层的形状：
#     papers        一篇一行：元数据、结论、局限、来源档次
#       ↑
#     samples       一篇多行：这个配方是什么、怎么做的
#       ↑
#     measurements  一个样品多行：一个数字一行，带条件与出处
#
# **老记录不用重抽也能进三层**：iter_measurements() 会把 v1 的 key_properties
# 拆成 sample_id='main'、location='' 的测量。空出处本身就是信息 ——
# 它精确地告诉你「这个数字还没定位到原文」。

SAMPLE_SCHEMA = {
    "sample_id":     "Short label used in the paper for this sample/formulation (e.g. 'PBS-1', 'PU-10%', 'neat PDMS'). If the paper reports only one material, use 'main'",
    "composition":   "What this sample is made of, with amounts/ratios if given (e.g. 'PDMS:boric acid = 10:1 wt')",
    "preparation":   "How this particular sample was made: temperature, time, atmosphere, with numbers",
    "dynamic_bond":  "Dynamic/reversible interaction in this sample; N/A if none",
    "role":          "Its role in the study: 'best' / 'control' / 'series' / 'reference'",
}

MEAS_SCHEMA = {
    "sample_id":  "Which sample this number belongs to (must match one sample_id above; use 'main' if the paper has only one material)",
    "name":       "Property name in plain English (e.g. 'tensile strength', 'elongation at break', 'self-healing efficiency', 'Mn')",
    "value_text": "The number with its unit exactly as printed (e.g. '12.4 MPa', '3.2x10^4 g/mol', '225-300 C'). Never convert units",
    "condition":  "Test condition if stated: strain rate, temperature, frequency, healing time, humidity. Empty string if not stated",
    "location":   "Where in the paper this number is printed: 'Table 2' / 'Fig. 3b' / 'main text' / 'SI Table S1'. Empty string if unsure",
    "section":    "'main' if it comes from the main text, 'si' if from the supplementary information",
}

# 抽取方式：这个数字是怎么来的。写论文引用前要看的第一眼。
METHOD_TEXT = 'text'          # 模型从正文/SI 文字里读出来的
METHOD_TEXT_V1 = 'text-v1'    # v1 老记录拆出来的，没有样品归属也没有出处
METHOD_CURVE = 'curve'        # 从曲线图上抠出来的（tools.digitize）
METHOD_HUMAN = 'human'        # 人手工核对/录入的，最可信


# ── 性能名字的统一词表 ────────────────────────────────────────────────
# 为什么必须归一：模型每篇写法都不一样（tensile strength / ultimate tensile
# stress / 拉伸强度 / σb）。不归一，「强度>10 MPa」这一句 SQL 就漏掉一半的库。
# **只归一名字，绝不归一单位**（单位换算错比查不到更难发现）。
PROPERTY_ALIASES = {
    'tensile strength':      ('tensile strength', 'ultimate tensile strength', 'ultimate tensile stress',
                              'tensile stress', 'fracture strength', 'breaking strength', 'strength at break',
                              '拉伸强度', '断裂强度'),
    'elongation at break':   ('elongation at break', 'strain at break', 'fracture strain', 'breaking elongation',
                              'elongation', '断裂伸长率', '断裂应变'),
    "young's modulus":       ("young's modulus", 'youngs modulus', 'elastic modulus', 'tensile modulus',
                              'modulus', '弹性模量', '杨氏模量'),
    'storage modulus':       ('storage modulus', "g'", '储能模量'),
    'loss modulus':          ('loss modulus', 'g"', '损耗模量'),
    'toughness':             ('toughness', 'work of fracture', 'fracture energy', 'energy dissipation', '韧性'),
    'self-healing efficiency': ('self-healing efficiency', 'self healing efficiency', 'healing efficiency',
                                'recovery efficiency', '自修复效率', '修复效率'),
    'mn':                    ('mn', 'number average molecular weight', 'number-average molecular weight'),
    'mw':                    ('mw', 'weight average molecular weight', 'weight-average molecular weight'),
    'pdi':                   ('pdi', 'polydispersity', 'polydispersity index', 'dispersity'),
    'viscosity':             ('viscosity', 'complex viscosity', 'zero-shear viscosity', 'shear viscosity', '粘度'),
    'glass transition temperature': ('glass transition temperature', 'tg', '玻璃化转变温度'),
    'thermal stability':     ('thermal stability', 'decomposition temperature', 'td', 't5%', '热分解温度'),
    'conductivity':          ('conductivity', 'ionic conductivity', 'electrical conductivity', '电导率', '离子电导率'),
    'gauge factor':          ('gauge factor', 'sensitivity', 'gf', '灵敏度'),
    'adhesion strength':     ('adhesion strength', 'adhesive strength', 'lap shear strength', 'peel strength',
                              '粘接强度', '剥离强度'),
    'hardness':              ('hardness', 'shore hardness', '硬度'),
    'impact strength':       ('impact strength', 'impact resistance', 'impact energy', 'ballistic limit',
                              '冲击强度', '抗冲击'),
    'crosslink density':     ('crosslink density', 'cross-link density', '交联密度'),
}

# 反查表：别名 → 正名。长别名优先匹配（'ultimate tensile strength' 要盖过 'tensile strength'）
_ALIAS_TO_CANON = sorted(
    ((a, canon) for canon, alist in PROPERTY_ALIASES.items() for a in alist),
    key=lambda x: -len(x[0]))


def normalize_property_name(name):
    """性能名字 → 统一词表里的正名；词表里没有的原样返回（小写去空白）。

    **只做名字归一，不碰单位、不碰数值。**词表外的名字照样入库 ——
    宁可库里多几个没归一的名字，也不要把它们悄悄丢掉。
    """
    t = re.sub(r'\s+', ' ', str(name or '')).strip().lower().strip('（）()[]:：')
    if not t:
        return ''
    if t in PROPERTY_ALIASES:
        return t
    for alias, canon in _ALIAS_TO_CANON:
        if alias == t or re.search(r'(^|[^a-z])' + re.escape(alias) + r'($|[^a-z])', t):
            return canon
    return t

# 系统提示词（「你是一台抽取引擎，不许编」那两段）不在这里 ——
# R5 窗起它们住 tools/extract/prompts/{main,eval}_v<N>.txt，由 tools.extract 读进来。
# 本块只回答「抽什么字段、怎么把字段拼进提问」，不回答「怎么跟模型说话」。


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
SOURCE_COARSE = 'coarse'    # Zotero 全文索引 + 本地小模型（tools.extract.batch.coarse_all）

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
    t = str(v).strip().lower()
    # 模型常写成「N/A (no explicit synthesis temperature given in the text)」——
    # 那依然是「没有」。不这么判，有值率会被这类句子灌水（2026-08-28 实测撞上）。
    if t.startswith('n/a') or t.startswith('not available') or t.startswith('未提及'):
        return False
    return t not in EMPTY_VALUES


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
# 查询时按名字 + 单位一起筛（见 tools/paperdb）。

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


# 「一句话里塞了好几条性能」怎么切：只在逗号后面**紧跟一个新的「名字:」**时才切。
# 为什么要这一条（2026-08-28 实测）：云端老老实实返回一个列表，
# 本地模型常返回一整个字符串 'Mn: 0.60 kg/mol, Mn: 0.56 kg/mol, …'。
# 不切开，本地就被算成「只抽到 1 条数值」—— 那是**格式差异，不是能力差异**，
# 拿这种指标去比模型，会得出错误结论。
_SPLIT_PROPS = re.compile(r'[;\n]|\s\|\s|,(?=\s*[A-Za-z一-龥][^:：,]{0,40}[:：])')


def parse_properties(record):
    """一条记录的 key_properties → 解析过的数值列表（拆不出数的也留着）。"""
    v = record.get('key_properties')
    if not v:
        return []
    items = []
    for chunk in (v if isinstance(v, (list, tuple)) else [v]):
        items += _SPLIT_PROPS.split(str(chunk))
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


# ── v2：样品与测量的读出口（老记录也走这里）──────────────────────────
# 这两个函数是**三层库的唯一入口**：编排环（tools/paperdb）只调它们，
# 不去关心一条记录到底是 v1 还是 v2 抽的。新旧混在一个库里也不会崩。

def samples_of(record):
    """一条记录 → 样品列表。

    v2 记录直接用它的 `samples`；**v1 老记录合成一个 'main' 样品**，
    把论文级的配方字段挪进去 —— 于是老数据不用重抽也能进三层，
    只是「这篇有几个配方」这一维暂时是塌的（等重抽才展开）。
    """
    raw = record.get('samples')
    out = []
    if isinstance(raw, (list, tuple)):
        for i, s in enumerate(raw):
            if not isinstance(s, dict):
                continue
            sid = str(s.get('sample_id') or f'S{i + 1}').strip() or f'S{i + 1}'
            out.append({'sample_id': sid,
                        'composition': _flat_text(s.get('composition')),
                        'preparation': _flat_text(s.get('preparation')),
                        'dynamic_bond': _flat_text(s.get('dynamic_bond')),
                        'role': _flat_text(s.get('role'))})
    if out:
        return out
    return [{'sample_id': 'main',
             'composition': _flat_text(record.get('precursors')),
             'preparation': _flat_text(record.get('synthesis_conditions')),
             'dynamic_bond': _flat_text(record.get('dynamic_bond_type')),
             'role': ''}]


def _flat_text(v):
    """列表/None → 一行文本（样品与测量字段都只存一行文本）。"""
    if v is None:
        return ''
    if isinstance(v, (list, tuple, set)):
        return '; '.join(str(x) for x in v if str(x).strip())
    return str(v).strip()


def iter_measurements(record):
    """一条记录 → 测量列表（一个数字一条，带条件、出处、抽取方式）。

    v2 走 `measurements`；v1 退回 `key_properties`，标 method='text-v1'、
    出处留空 —— **空出处本身就是信息**：它精确地说「这个数字还没定位到原文」，
    于是「哪些数字能直接写进论文」变成一句 SQL，而不是靠记忆。
    """
    out = []
    raw = record.get('measurements')
    if isinstance(raw, (list, tuple)) and raw:
        for m in raw:
            if not isinstance(m, dict):
                continue
            name = _flat_text(m.get('name'))
            text = _flat_text(m.get('value_text')) or _flat_text(m.get('value'))
            if not (name or text):
                continue
            parsed = parse_property(f'{name}: {text}' if name else text)
            out.append({
                'sample_id': _flat_text(m.get('sample_id')) or 'main',
                'name': normalize_property_name(name or parsed['name']),
                'raw_name': name or parsed['name'],
                'value': parsed['value'], 'value_max': parsed['value_max'],
                'unit': parsed['unit'], 'cmp': parsed['cmp'],
                'condition': _flat_text(m.get('condition')),
                'location': _flat_text(m.get('location')),
                'section': (_flat_text(m.get('section')) or 'main').lower(),
                'method': _flat_text(m.get('method')) or METHOD_TEXT,
                'raw': f'{name}: {text}'.strip(': '),
            })
        return out
    for p in parse_properties(record):
        out.append({'sample_id': 'main',
                    'name': normalize_property_name(p['name']), 'raw_name': p['name'],
                    'value': p['value'], 'value_max': p['value_max'],
                    'unit': p['unit'], 'cmp': p['cmp'],
                    'condition': '', 'location': '',
                    'section': 'si' if record.get('si_used') else 'main',
                    'method': METHOD_TEXT_V1, 'raw': p['raw']})
    return out


def build_user_prompt_v2(title, body, si=''):
    """v2 抽取提问：论文级字段 + **样品清单** + **一条一个数字的测量清单**。

    与 v1 的区别只有一件事，但它决定了整个库能不能用：
    **要求模型说清每个数字属于哪个样品、在什么条件下测的、印在原文哪儿。**
    没有这三样，跨论文比大小就是在比假数，写论文时也不敢引。
    """
    fields = "\n".join(f'  - "{k}": {v}' for k, v in SAMPLE_SCHEMA.items())
    meas = "\n".join(f'  - "{k}": {v}' for k, v in MEAS_SCHEMA.items())
    p = (
        f"Paper title: {title}\n\n"
        "Return ONE JSON object with these three parts.\n\n"
        "PART 1 - paper-level fields (same keys as before):\n"
        f"{_field_list()}\n\n"
        'PART 2 - "samples": a list, ONE ENTRY PER MATERIAL/FORMULATION the paper reports.\n'
        "If the paper reports a series (PBS-1, PBS-2, ...), list them all. Fields:\n"
        f"{fields}\n\n"
        'PART 3 - "measurements": a list, ONE ENTRY PER NUMBER. Fields:\n'
        f"{meas}\n\n"
        "Rules for measurements (these matter more than coverage):\n"
        "  * Copy numbers and units EXACTLY as printed. Never convert units.\n"
        '  * Every measurement must name a sample_id that appears in "samples".\n'
        '  * If you cannot tell where a number is printed, leave "location" empty '
        "rather than guessing. A guessed location is worse than an empty one.\n"
        "  * Do not invent numbers. If the paper only shows a curve without a stated "
        "value, skip it.\n\n"
        f"===== MAIN TEXT START =====\n{body}\n===== MAIN TEXT END ====="
    )
    if si and si.strip():
        p += (
            f"\n\n===== SUPPLEMENTARY INFORMATION START =====\n{si}\n"
            "===== SUPPLEMENTARY INFORMATION END =====\n\n"
            "The supplementary information belongs to this same paper and usually holds "
            "the exact recipe (amounts, ratios, concentrations, temperature, time) and "
            "extra tables of numbers. Use it for \"samples\" and for measurements with "
            "section='si'."
        )
    return p


def provenance_stats(measurements):
    """这批数字有多少能追溯：{'n', 'located', 'with_condition', 'with_sample', 'numeric'}。

    这是三层库的体温计 —— 「能不能直接写进论文」看的就是 located 这一栏。
    """
    ms = list(measurements)
    return {'n': len(ms),
            'numeric': sum(1 for m in ms if m.get('value') is not None),
            'located': sum(1 for m in ms if has_value(m.get('location'))),
            'with_condition': sum(1 for m in ms if has_value(m.get('condition'))),
            'with_sample': sum(1 for m in ms if (m.get('sample_id') or 'main') != 'main')}
