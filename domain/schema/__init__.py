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
  - is_review                : 这篇是不是综述（决定进哪张表）
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


def build_user_prompt(title, body):
    return (
        f"Paper title: {title}\n\n"
        f"Extract the following fields as JSON (keys are the English field names, values in English, keep original units):\n"
        f"{_field_list()}\n\n"
        f"===== TEXT START =====\n{body}\n===== TEXT END ====="
    )


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


def compare_table(records):
    """研究论文的横向对比表（Markdown 字符串）。**不写盘** —— 写哪去是编排环的事。"""
    research = [r for r in records if not is_review(r)]
    reviews = [r for r in records if is_review(r)]
    rows = ["# 结构化抽取 · 横向对比表（仅研究论文）", "",
            "> 自动生成。竖着比同一字段，找矛盾、空白、规律。",
            f"> 研究论文 {len(research)} 篇；综述 {len(reviews)} 篇已分流到 compare_reviews.md"
            f"（综述无单一体系数值，不入本表）。", ""]
    header = ['论文'] + COMPARE_COLS
    rows.append('| ' + ' | '.join(header) + ' |')
    rows.append('|' + '---|' * len(header))
    for r in research:
        cells = [str(r.get('title', ''))[:30]] + [
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


def make_record(key, title, doi, data, schema_ver=None):
    """抽取结果 → 落盘用的记录。**带上版本号**，否则以后没法知道它是哪版 schema 抽的。"""
    return {'key': key, 'title': title, 'doi': doi or '',
            'schema_ver': SCHEMA_VER if schema_ver is None else schema_ver, **data}
