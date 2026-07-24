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
import os, json, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBRARY = os.path.join(ROOT, 'workflow_data', 'library')
OUT_DIR = os.path.join(ROOT, 'workflow_data', 'structured')
os.makedirs(OUT_DIR, exist_ok=True)

DEEPSEEK_KEY = os.environ.get('DEEPSEEK_KEY', '***REMOVED***')
DEEPSEEK_MODEL = 'deepseek-v4-pro'   # 抽取要准，用 pro；不追求快
# provider 开关：默认 deepseek（云）；设 EXTRACT_PROVIDER=ollama 走本地大模型，省 API 费
PROVIDER = os.environ.get('EXTRACT_PROVIDER', 'deepseek').lower()
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen2.5:7b-instruct')
REBUILD = '--rebuild' in sys.argv
ONLY_KEY = next((a for a in sys.argv[1:] if not a.startswith('--')), None)

# ── 领域定制 schema：软物质 / 动态键弹性体 / 自愈合 ─────────────────────
# 每个字段的说明会直接进 prompt，指导模型抽什么。改方向 = 改这里。
SCHEMA = {
    "material_system":     "核心材料体系（如 PBS聚硼硅氧烷、PDMS基弹性体、动态相锁粘合剂等），一句话",
    "dynamic_bond_type":   "提供可逆/动态交联的相互作用类型（氢键、硼氧键B-O-B、金属配位、相分离纳米畴等）",
    "precursors":          "主要原料/前驱体及配比（如 PDMS:硼酸 = 10:1）",
    "synthesis_conditions":"关键合成/加工条件，务必带数值（温度、时间、气氛等）",
    "characterization":    "主要表征手段列表（如 GPC、FTIR、流变、SAXS）",
    "key_properties":      "任何量化表征结果——不限于力学，涵盖力学（拉伸强度/韧性/模量）、分子量（Mn/Mw/PDI）、流变/黏度、热稳定性、电导率/离子电导率、传感灵敏度、自愈合效率等。每项写成 '性质名: 数值+单位'（如 '拉伸强度: 12 MPa'、'Mn: 3.2×10^4 g/mol'、'复数黏度: 1.5×10^3 Pa·s'、'离子电导率: 8.2×10^-5 S/cm'）。只要原文报了带单位的量化结果就抽，无数值才留 N/A",
    "self_healing":        "是否具备自愈合/可逆性，及其机制一句话；没有则 N/A",
    "structure_property":  "论文点明的结构-性能因果关系（什么结构特征导致什么性能变化）",
    "key_finding":         "本文最核心的发现/创新点，一句话",
    "limitation":          "论文自述的局限或未解决问题；没提则 N/A",
    "doc_type":            "文献类型：研究论文填 research；综述/review/进展/perspective 填 review。综述不套单一体系的数值字段。",
}

SYS = (
    "你是材料科学文献结构化抽取引擎。只依据给定正文抽取信息，严禁编造或外推。"
    "找不到的字段一律填 \"N/A\"。数值必须连同单位一起抽，保留原文有效数字，不要换算。"
    "只输出一个 JSON 对象，不要任何解释、不要 markdown 代码围栏。"
)

def build_user_prompt(title, body):
    fields = "\n".join(f'  - "{k}": {v}' for k, v in SCHEMA.items())
    return (
        f"论文标题：{title}\n\n"
        f"请抽取以下字段，输出为 JSON（键用英文字段名，值用中文，数值保留原文单位）：\n"
        f"{fields}\n\n"
        f"===== 正文开始 =====\n{body}\n===== 正文结束 ====="
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
    body = json.dumps({
        'model': DEEPSEEK_MODEL, 'temperature': 0.1,
        'response_format': {'type': 'json_object'},
        'messages': [{'role': 'system', 'content': system},
                     {'role': 'user', 'content': user}]
    }, ensure_ascii=False).encode()
    req = urllib.request.Request('https://api.deepseek.com/chat/completions',
        data=body, method='POST',
        headers={'Authorization': f'Bearer {DEEPSEEK_KEY}', 'Content-Type': 'application/json'})
    txt = json.loads(urllib.request.urlopen(req, timeout=240).read())['choices'][0]['message']['content']
    return json.loads(txt)

def ollama_json(system, user):
    """本地 Ollama 分支：走 localhost:11434，format=json 强制 JSON 输出。"""
    body = json.dumps({
        'model': OLLAMA_MODEL, 'stream': False, 'format': 'json',
        'options': {'num_ctx': 16384, 'temperature': 0.1},
        'messages': [{'role': 'system', 'content': system},
                     {'role': 'user', 'content': user}]
    }, ensure_ascii=False).encode()
    req = urllib.request.Request('http://localhost:11434/api/chat',
        data=body, method='POST', headers={'Content-Type': 'application/json'})
    txt = json.loads(urllib.request.urlopen(req, timeout=600).read())['message']['content']
    return json.loads(txt)

def llm_json(system, user):
    return ollama_json(system, user) if PROVIDER == 'ollama' else deepseek_json(system, user)

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
    data = llm_json(SYS, build_user_prompt(title, body))
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
            print(f'[出错] {key}: {e}')
    # 汇总所有已抽取的结果成对比表
    all_recs = [json.load(open(os.path.join(OUT_DIR, f), encoding='utf-8'))
                for f in sorted(os.listdir(OUT_DIR)) if f.endswith('.json')]
    if all_recs:
        build_compare_table(all_recs)
    print(f'\n完成：共 {len(all_recs)} 篇结构化记录 → {OUT_DIR}')
    print(f'对比表：{os.path.join(OUT_DIR, "compare.md")}')

if __name__ == '__main__':
    main()
