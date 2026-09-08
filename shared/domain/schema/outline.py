# -*- coding: utf-8 -*-
"""outline · 一篇论文 → **稳定的骨架**（给模型点菜用的菜单）。纯逻辑，不联网、不知道文件在哪。

## 解决的真实问题

全文平均 49995 字符（42 篇实测），约 1.3 万 token。模型读三篇就把上下文吃掉一半，
而一个问题真正需要的往往是两三节、不到 5000 字符。

所以别把整篇端上去 —— **先给菜单，让它点。**

    L0 卡片   题录 + 结论一句话        判断这篇值不值得读
    L1 目录   每节的类别/字数/含多少数字/表图   ← 本模块产出这一层
    L2 切片   按地址取原文（一节 / 一张表）
    L3 数值   已抽好的结构化数据（tools/paperdb）

## 为什么按「功能类别」而不是标题字面

论文的标题**根本不统一**：Results 和 Discussion 有时合并、有时纯数字编号、
Experimental 还是 Methods 看期刊，MineRU 偶尔还把图注识别成标题。
按字面根本对不齐，所以固定的是**类别**，不是标题。

## 类别的用处不止省 token

`背景` 这一类被明确标出来之后，等于告诉模型「**这一节里的数字是别人的**」——
2026-09-08 金标实测的硬错误里，最常见的一类就是把引言里引用的他人数据
（Yang 等人的 797.4 MPa）当成本文材料的性能。类别是这个错的解药。

## 契约

    build_outline(md, si_md='') -> dict
        {'sections': [{'id','title','kind','chars','n_numbers','n_tables',
                       'n_figures','samples','start','end'}, ...],
         'tables': [...], 'figures': [...], 'stats': {...}}

    section_text(md, outline, sec_id) -> str      # 按地址取原文

**认不出就标 `未分类`，不猜。** 空类别是事实，猜一个是错。
"""
import re

from . import scan

# ── 类别（通用材料类论文，不按具体方向定制）──────────────────────────
# 判据：**模型问一个问题时，会不会只想看这一类**。会 → 单独一类。
# 太细的分类没人用得上，还会把「归类失败」的概率抬高。
ABSTRACT = '摘要'
BACKGROUND = '背景'          # 引言、文献综述 —— 里面的数字多半是别人的
SYNTHESIS = '合成'           # 原料、配方、制备步骤
METHODS = '方法'             # 表征仪器、测试条件、计算细节
RESULTS = '结果'             # 性能数据（最常被点的一类）
DISCUSSION = '讨论'          # 机理、结构-性能关系
CONCLUSION = '结论'
NONBODY = '非正文'           # 参考文献、致谢、作者信息、版权
UNKNOWN = '未分类'

KINDS = (ABSTRACT, BACKGROUND, SYNTHESIS, METHODS, RESULTS, DISCUSSION,
         CONCLUSION, NONBODY, UNKNOWN)

# 标题关键词 → 类别。**顺序即优先级**：先匹配到的赢。
# 「results and discussion」要在「discussion」前面，否则合并章节会被归成讨论。
_RULES = (
    (NONBODY, r'reference|bibliograph|acknowledg|author|'
              r'conflict|competing\s+interest|funding|orcid|copyright|'
              r'associated\s+content|supporting\s+information|'
              r'received.*accepted|published\s+online|data\s+availability|'
              r'附录|参考文献|致谢'),
    (ABSTRACT, r'^abstract|^a\s*b\s*s\s*t\s*r\s*a\s*c\s*t|graphical\s+abstract|'
               r'^summary$|摘要|^highlights?$'),
    (CONCLUSION, r'conclusion|concluding|outlook|perspective\s*$|^summary\b|总结|结论'),
    (RESULTS, r'result.*discussion|discussion.*result|^results?\b|performance|'
              r'properties|characteriz.*result|application|sensing|结果|应用'),
    (SYNTHESIS, r'synthes|preparation|fabricat|materials?\s*(and|&)?\s*(reagents?)?$|'
                r'^materials?\b|sample\s+preparation|制备|合成'),
    (METHODS, r'method|experimental|characteriz|measurement|instrument|'
              r'\btests?\b|testing|computational|simulation\s+detail|apparatus|'
              r'方法|表征|测试'),
    (DISCUSSION, r'discussion|mechanism|analysis|机理|讨论'),
    # Nature/Science 风格的论文用**描述性小标题**，全篇没有 Results 字样：
    # 「Anti-impact ability of PDBS」「Thermal stiffening behavior of PDU-PDBA」
    # 「Autonomous Self-Healing Property」「The effect of the B/Si atomic ratio」
    # —— 这些全是结果章。实测 43 篇里有 6 篇因此大面积未分类。
    (RESULTS, r'\babilit|behaviou?r|propert|stabilit|effects?\s+of|influence\s+of|'
              r'\bversus\b|dependence|comparison\s+of'),
    (BACKGROUND, r'introduction|background|literature\s+review|引言|前言|绪论'),
)
_RULES = tuple((kind, re.compile(pat, re.I)) for kind, pat in _RULES)

# 「实验部分」下面的子节要不要继承父节的类别 —— 要。
# `## 2. Experimental` / `### 2.1 Materials` / `### 2.3 Mechanical property test`
# 里，2.1 该是合成、2.3 该是方法，各自的标题就够判；判不出的才继承父节。
_FIG_RE = re.compile(r'(?im)^\s*(?:!\[\]|.*?)\bfig(?:ure)?\.?\s*(\d+[a-z]?)\b')
_TAB_RE = re.compile(r'(?im)\btable\s*(\d+[a-z]?)\b')


def classify(title, parent_kind=''):
    """一个标题 → 类别。认不出就返回 `未分类`（**不猜**）。

    `parent_kind` 是上一级标题的类别：子节自己判不出来时继承它 ——
    `### 2.1 Materials` 单看能判成合成，而 `### 2.4 General procedure`
    单看判不出，但它显然属于父节「实验部分」。
    """
    t = scan.clean_label(title or '').strip()
    # 去掉编号前缀（`2.1.` / `II.` / `一、`），它们对判类别没有信息。
    # ⚠ **分隔符必须存在**（2026-09-08 全库实测）：原来写成
    # `^[\dIVXivx]+[.)、]?\s*`，分隔符可有可无，于是 `INTRODUCTION` 开头那个
    # `I` 被当成罗马数字剥掉，变成 `NTRODUCTION` —— 43 篇里**每一篇的引言**
    # 都成了「未分类」，而且看统计完全看不出原因。
    t = re.sub(r'^(?:\d+(?:\.\d+)*[.)]?|[IVXivx]+[.)]|[一二三四五六七八九十]+[、.])\s+',
               '', t).strip()
    if not t:
        return parent_kind or UNKNOWN
    if _ALL_CJK.match(t):          # 纯中文标题 = 中文题名/中文摘要
        return ABSTRACT
    for kind, pat in _RULES:
        if pat.search(t):
            return kind
    return parent_kind or UNKNOWN


_ALL_CJK = re.compile(r'^[\u4e00-\u9fa5\uff08\uff09\uff0c\u3001\uff1a\s'
                      r'\u2014\u2018\u2019\u201c\u201d0-9-]+$')
_NUM_PREFIX = re.compile(r'^\s*(\d+(?:\.\d+)*)\.?\s')


def _level(line):
    m = re.match(r'^(#{1,6})\s', line)
    return len(m.group(1)) if m else 0


def _depth(title, hash_level):
    """这个标题在**逻辑上**有多深。

    为什么不能只看 `#` 的个数（2026-09-08 实测）：`## 3. Results and discussion`
    与 `## 3.1. Surface modification` 在 markdown 里**同级**，
    于是 3.1 认不出自己属于「结果」那一章 —— 父子关系断在这里。
    而编号 `3` 与 `3.1` 把真实层级写得清清楚楚，优先用它。
    """
    m = _NUM_PREFIX.match(scan.clean_label(title or ''))
    if m:
        return 10 + m.group(1).count('.')      # 10、11、12…，与 # 级别分开不打架
    return hash_level


def build_outline(md, si_md=''):
    """全文 → 骨架。**纯派生**：随时可从 `full.md` 重建，删了不心疼。

    每一节带四个「值不值得读」的信号：字数、有多少个数字、几张表、几张图。
    模型据此点菜 —— 问性能就去数字多的那节，问怎么做的就去合成那节。
    """
    text = scan.clean_body(md or '')
    lines = text.splitlines(keepends=True)
    heads, pos = [], 0
    for ln in lines:
        lv = _level(ln)
        if lv:
            heads.append({'level': lv, 'title': ln.strip('#').strip(), 'start': pos})
        pos += len(ln)
    total = len(text)

    # 每节的范围 = 从它的标题到下一个**同级或更高级**标题之前
    stack, sections = [], []
    for i, h in enumerate(heads):
        depth = _depth(h['title'], h['level'])
        # 一级标题且在文首 = **论文题目**，不是一个章节，更不该当父节：
        # 「Synthesis of Structure-Controlled Polyborosiloxanes...」会把整篇
        # 都带成「合成」，连 INTRODUCTION 都跟着错（2026-09-08 实测）。
        is_title = (i == 0 and h['level'] <= 1 and h['start'] < 200)
        # **字数只算自己那一段**（到下一个标题为止），不含子节 ——
        # 含子节的话「3. 结果」会把 3.1~3.4 全算进去，菜单里每一节都虚胖，
        # 各节字数加起来还会超过全文（实测 121%）。
        end = heads[i + 1]['start'] if i + 1 < len(heads) else total
        # 取原文时才需要「连同子节」的范围
        end_tree = total
        for nxt in heads[i + 1:]:
            if _depth(nxt['title'], nxt['level']) <= depth:
                end_tree = nxt['start']
                break
        while stack and stack[-1]['depth'] >= depth:
            stack.pop()
        parent = stack[-1]['kind'] if stack else ''
        kind = ABSTRACT if is_title else classify(h['title'], parent)
        body = text[h['start']:end]
        sections.append({
            'id': 's%d' % (len(sections) + 1),
            'title': h['title'][:120],
            'kind': kind,
            'level': h['level'],
            'start': h['start'],
            'end': end,
            'end_tree': end_tree,
            'chars': len(body),
            'n_numbers': len(scan.scan_numbers(body)),
            'n_tables': len(set(_TAB_RE.findall(body))),
            'n_figures': len(set(_FIG_RE.findall(body))),
        })
        if not is_title:                      # 论文题目不进继承栈
            stack.append({'depth': depth, 'kind': kind})

    # 标题之前的那一段（题录、作者、摘要常在这里）也要有个位置
    if heads and heads[0]['start'] > 200:
        head_body = text[:heads[0]['start']]
        sections.insert(0, {
            'id': 's0', 'title': '（正文开头，无标题）', 'kind': ABSTRACT,
            'level': 0, 'start': 0, 'end': heads[0]['start'],
            'chars': len(head_body), 'n_numbers': len(scan.scan_numbers(head_body)),
            'n_tables': 0, 'n_figures': 0})

    tables = scan.scan_tables(text)
    by_kind = {}
    for s in sections:
        by_kind[s['kind']] = by_kind.get(s['kind'], 0) + s['chars']
    out = {
        'sections': sections,
        'tables': sorted({t.get('location', '') for t in tables if t.get('location')}),
        'n_table_rows': len(tables),
        'stats': {'chars': total, 'n_sections': len(sections),
                  'chars_by_kind': by_kind,
                  'unknown_ratio': round(
                      by_kind.get(UNKNOWN, 0) / total, 3) if total else 0.0},
    }
    if si_md:
        si = build_outline(si_md)
        out['si'] = {'sections': si['sections'], 'stats': si['stats']}
    return out


def section_text(md, outline, sec_id, with_subsections=True):
    """按地址取原文。地址就是 `outline` 里的 `id`。取不到返回空串。

    默认**连同子节**：点「3. 结果」要的显然是整章，不是那行标题。
    只要本节自己那一段时传 `with_subsections=False`。
    """
    text = scan.clean_body(md or '')
    for s in outline.get('sections') or []:
        if s['id'] == sec_id:
            end = s.get('end_tree', s['end']) if with_subsections else s['end']
            return text[s['start']:end]
    return ''


def menu(outline, skip=(NONBODY,)):
    """骨架 → **给模型看的菜单**（几百 token，不是几万）。

    默认把参考文献那类滤掉：它字数多、数字多，但一条本文的性能都没有，
    留在菜单里只会诱导模型去点它。
    """
    rows = []
    for s in outline.get('sections') or []:
        # 非正文默认隐藏（参考文献数字多、性能一条没有，留着只会诱导模型去点）。
        # **但大块的不隐藏**：MineRU 常把投稿信息识别成标题，后面挂着上万字真正文
        # （实测有一篇 13462 字）—— 一刀切隐藏会把正文一起弄丢。
        if s['chars'] < 80 or (s['kind'] in skip and s['chars'] < 2000):
            continue
        bits = ['%s [%s] %s' % (s['id'], s['kind'], s['title'][:60]),
                '%d 字' % s['chars']]
        if s['n_numbers']:
            bits.append('%d 个数' % s['n_numbers'])
        if s['n_tables']:
            bits.append('%d 表' % s['n_tables'])
        if s['n_figures']:
            bits.append('%d 图' % s['n_figures'])
        rows.append(' · '.join(bits))
    return '\n'.join(rows)
