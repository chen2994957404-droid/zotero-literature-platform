# -*- coding: utf-8 -*-
"""结构化抽取（粗层 / 广度抽取）：把每篇文献的 full.md 按软物质·动态键弹性体方向的
schema，用 DeepSeek 抽成对齐的机器可读 JSON。这是"向量检索"之外的第二条线——
让全库从"可语义检索"升级为"可筛选、可聚合、可横向对比"。

设计要点（对齐领域最佳实践）：
  1. schema 贴合方向（超分子/动态键弹性体、自愈合、结构-性能），字段可直接用于筛选与对比
  2. 数值型字段强制带 value+unit+出处片段，防止单位/有效数字在下游传播中出错
  3. 每个字段允许 "N/A"，模型找不到就留空，绝不编造（降低幻觉）
  4. 抽完自动汇总成一张对齐的对比表（compare.md），这就是"idea 从横向对比中产生"的载体

用法:
  python extract_structured.py              # 抽取所有未处理的文献（增量）
  python extract_structured.py --rebuild    # 重抽全部
  python extract_structured.py <KEY>        # 只抽某一篇
"""
import os, sys, json, re

# 【标准开头】项目根加入 import 路径 + 强制 UTF-8 输出（详见 docs/代码规范_标准脚本模板.md）
_ROOT = os.path.dirname(os.path.abspath(__file__))
while True:
    if os.path.isdir(os.path.join(_ROOT, 'modules')):
        break                      # 项目根特征：modules/ 目录只在根存在
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        break                      # 到盘符根，兜底
    _ROOT = parent
sys.path.insert(0, _ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from modules.cli import flag, pos
from modules.config import get_key, get_model
# LLM 调用已收敛到公理件 modules/llm_client（消除 6 处重复实现，见踩坑 #17）
from modules.llm_client import chat_json as _chat_json

LIBRARY = os.path.join(_ROOT, 'workflow_data', 'library')
OUT_DIR = os.path.join(_ROOT, 'workflow_data', 'structured')
os.makedirs(OUT_DIR, exist_ok=True)

DEEPSEEK_KEY = get_key('DEEPSEEK_KEY')
DEEPSEEK_MODEL = get_model('EXTRACT_MODEL')  # 抽取要准，用 pro；可在控制面板切换
# provider 开关：默认 deepseek（云）；设 EXTRACT_PROVIDER=ollama 走本地大模型，省 API 费
PROVIDER = os.environ.get('EXTRACT_PROVIDER', 'deepseek').lower()
OLLAMA_MODEL = get_key('OLLAMA_MODEL', default='qwen2.5:7b-instruct')
REBUILD = flag('--rebuild')
ONLY_KEY = pos(0)

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

SYS = (
    "You are a materials-science literature structured-extraction engine. Extract information "
    "only from the given text; never fabricate or extrapolate. Fill any field you cannot find "
    "with \"N/A\". Always extract numbers together with their units, keep the original significant "
    "figures, do not convert. Output exactly one JSON object, no explanation, no markdown code fences. "
    "All values in English (native, machine-readable)."
)

def build_user_prompt(title, body):
    fields = "\n".join(f'  - "{k}": {v}' for k, v in SCHEMA.items())
    return (
        f"Paper title: {title}\n\n"
        f"Extract the following fields as JSON (keys are the English field names, values in English, keep original units):\n"
        f"{fields}\n\n"
        f"===== TEXT START =====\n{body}\n===== TEXT END ====="
    )

def strip_refs(md):
    """去掉参考文献之后的部分（复用 vectorize.py 的思路）"""
    pat = re.compile(r'(?im)^\s*#{0,4}\s*(references|reference|bibliography|参考文献|literature\s+cited)\s*$')
    m = pat.search(md)
    cut = m.start() if m else len(md)
    body = md[:cut].strip()
    return body if len(body) > len(md) * 0.2 else md

def hierarchical_body(md, budget=14000):
    """层次化取正文（优于固定截断）：去参考文献、去图片标记，若仍超预算，
    优先保留 摘要+引言+实验/方法+结论 这些高信息密度章节。"""
    md = strip_refs(md)
    md = re.sub(r'!\[\]\(images/[^)]+\)', '', md)          # 去图片
    if len(md) <= budget:
        return md
    # 超预算：按标题切段，优先保留关键章节
    priority = re.compile(r'(?i)(abstract|introduction|experiment|method|result|discussion|conclusion|摘要|引言|实验|方法|结果|结论)')
    blocks = re.split(r'(?m)^(#{1,3}\s.*)$', md)
    kept, used = [md[:1500]], 1500                          # 开头（含摘要）一定保留
    for i in range(1, len(blocks) - 1, 2):
        head, content = blocks[i], blocks[i + 1]
        seg = head + content
        if priority.search(head) and used + len(seg) < budget:
            kept.append(seg); used += len(seg)
    return "\n".join(kept)

def deepseek_json(system, user):
    """保留名字供 extract_batch import；实际走公理件（云端）。"""
    return _chat_json(system, user, provider='deepseek', model=DEEPSEEK_MODEL, key=DEEPSEEK_KEY)

def llm_json(system, user):
    """按 PROVIDER 分流到公理件（云/本地）。"""
    if PROVIDER == 'ollama':
        return _chat_json(system, user, provider='ollama', model=OLLAMA_MODEL)
    return _chat_json(system, user, provider='deepseek', model=DEEPSEEK_MODEL, key=DEEPSEEK_KEY)

# ── 自我评估循环（借鉴 KnowMat 骨架，用自己公理件实现，不依赖 LangGraph）──
# 抽完对照原文自检：漏抽/幻觉 → 反馈重抽。默认开，EXTRACT_NO_EVAL=1 可关（省钱）。
_EVAL_ENABLED = os.environ.get('EXTRACT_NO_EVAL', '') != '1'
_EVAL_SYS = (
    "You are a strict extraction QA checker. Given the source text, an extraction schema, "
    "and an extracted JSON, check two things: (1) MISSED — fields marked N/A but whose data "
    "actually appears in the source; (2) HALLUCINATED — values in the JSON that cannot be found "
    "in the source. Output one JSON: {\"ok\": true/false, \"missed\": [\"field: what was missed\"], "
    "\"hallucinated\": [\"field: the value not in source\"]}. If clean, ok=true and empty lists. "
    "No explanation, no code fences."
)

def _evaluate(title, body, data):
    """对照原文检查抽取结果，返回 {ok, missed, hallucinated}。"""
    fields = "\n".join(f'  - "{k}": {v}' for k, v in SCHEMA.items())
    user = (f"Schema:\n{fields}\n\nExtracted JSON:\n{json.dumps(data, ensure_ascii=False)}\n\n"
            f"===== SOURCE TEXT =====\n{body}\n===== END =====")
    try:
        return _chat_json(_EVAL_SYS, user, provider='deepseek', model=DEEPSEEK_MODEL, key=DEEPSEEK_KEY)
    except Exception as e:
        # 自检失败不算抽取失败：返回 ok 让主流程继续（评估只是质量增强，缺了不影响产出）
        return {'ok': True, 'missed': [], 'hallucinated': [], '_eval_error': str(e)}

def extract_with_eval(title, body, max_cycles=2):
    """抽取 + 自我评估重抽循环（借鉴 KnowMat）。返回 (data, eval_report)。"""
    data = llm_json(SYS, build_user_prompt(title, body))
    if not _EVAL_ENABLED or PROVIDER == 'ollama':   # 本地模型评估不可靠，跳过
        return data, {'ok': None, 'note': 'eval skipped'}
    for cycle in range(max_cycles):
        report = _evaluate(title, body, data)
        if report.get('ok') is True or (not report.get('missed') and not report.get('hallucinated')):
            return data, report
        # 有问题 → 带反馈重抽
        fb = (f"Your previous extraction had issues. MISSED: {report.get('missed')}. "
              f"HALLUCINATED (remove or fix these): {report.get('hallucinated')}. "
              f"Re-extract correctly.")
        print(f'  [自检第{cycle+1}轮] 漏抽{len(report.get("missed",[]))} 幻觉{len(report.get("hallucinated",[]))}，重抽')
        data = llm_json(SYS, build_user_prompt(title, body) + "\n\n" + fb)
    return data, report

def extract_one(key):
    d = os.path.join(LIBRARY, key)
    md_path = os.path.join(d, 'parsed', 'full.md')
    meta_path = os.path.join(d, 'meta.json')
    if not os.path.exists(md_path):
        print(f'[跳过] {key} 无 full.md'); return None
    meta = json.load(open(meta_path, encoding='utf-8')) if os.path.exists(meta_path) else {}
    title = meta.get('title', key)
    body = hierarchical_body(open(md_path, encoding='utf-8').read())
    print(f'[抽取] {title[:50]} …')
    data, _report = extract_with_eval(title, body)
    record = {'key': key, 'title': title, 'doi': meta.get('DOI', ''), **data}
    json.dump(record, open(os.path.join(OUT_DIR, f'{key}.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    return record

def _is_review(r):
    """判断是否综述：优先信 doc_type，兜底看标题特征词。"""
    dt = str(r.get('doc_type', '')).lower()
    if 'review' in dt:
        return True
    t = (r.get('title') or '').lower()
    return any(w in t for w in ('review', 'overview', 'recent advances', 'recent progress',
                                'a survey', 'perspective', '综述', '研究进展', '进展'))

def build_compare_table(records):
    """把研究论文汇成对齐对比表；综述分流单列，不混进数值对比（工单·综述分流）。"""
    research = [r for r in records if not _is_review(r)]
    reviews  = [r for r in records if _is_review(r)]
    rows = ["# 结构化抽取 · 横向对比表（仅研究论文）", "",
            "> 由 extract_structured.py 自动生成。竖着比同一字段，找矛盾、空白、规律。",
            f"> 研究论文 {len(research)} 篇；综述 {len(reviews)} 篇已分流到 compare_reviews.md（综述无单一体系数值，不入本表）。", ""]
    cols = ['material_system', 'dynamic_bond_type', 'synthesis_conditions',
            'key_properties', 'self_healing', 'key_finding']
    header = ['论文'] + cols
    rows.append('| ' + ' | '.join(header) + ' |')
    rows.append('|' + '---|' * len(header))
    for r in research:
        cells = [r['title'][:30]] + [str(r.get(c, 'N/A')).replace('\n', ' ')[:80] for c in cols]
        rows.append('| ' + ' | '.join(cells) + ' |')
    open(os.path.join(OUT_DIR, 'compare.md'), 'w', encoding='utf-8').write('\n'.join(rows))
    # 综述单列一张精简清单（只留标题/核心发现/局限，供综述式检索）
    if reviews:
        rrows = ["# 综述清单（从对比表分流）", "",
                 "> 这些是综述/进展类文献，不套研究论文的数值 schema。适合了解领域全景、进问答库。", "",
                 "| 论文 | 核心发现 | 局限 |", "|---|---|---|"]
        for r in reviews:
            rrows.append('| ' + ' | '.join([r['title'][:40],
                str(r.get('key_finding', 'N/A')).replace('\n', ' ')[:90],
                str(r.get('limitation', 'N/A')).replace('\n', ' ')[:60]]) + ' |')
        open(os.path.join(OUT_DIR, 'compare_reviews.md'), 'w', encoding='utf-8').write('\n'.join(rrows))

def main():
    if ONLY_KEY:
        keys = [ONLY_KEY]
    else:
        keys = sorted(k for k in os.listdir(LIBRARY)
                      if os.path.isdir(os.path.join(LIBRARY, k)))
    records = []
    for key in keys:
        out = os.path.join(OUT_DIR, f'{key}.json')
        if os.path.exists(out) and not REBUILD and not ONLY_KEY:
            print(f'[已存在] {key}'); records.append(json.load(open(out, encoding='utf-8'))); continue
        try:
            rec = extract_one(key)
            if rec: records.append(rec)
        except Exception as e:
            print(f'[出错] {key}: {e}')   # 单篇失败报出来继续下一篇，不中断整批
    # 汇总所有已抽取的结果成对比表
    all_recs = [json.load(open(os.path.join(OUT_DIR, f), encoding='utf-8'))
                for f in sorted(os.listdir(OUT_DIR)) if f.endswith('.json')]
    if all_recs:
        build_compare_table(all_recs)
    print(f'\n完成：共 {len(all_recs)} 篇结构化记录 → {OUT_DIR}')
    print(f'对比表：{os.path.join(OUT_DIR, "compare.md")}')

if __name__ == '__main__':
    main()
