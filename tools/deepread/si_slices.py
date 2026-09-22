# -*- coding: utf-8 -*-
"""SI 全文 → 四份材料（原料 / 逐流程 / 表征 / 图表），给 SI 精读的四次调用各拿各的。

2026-09-22 之前 SI 精读是 3 万字符一口气喂给模型、一次写四栏 —— 那正是本地模型做不好的形状
（本地化拆解规划 §2.1）；超过 3 万的 SI（80k 的有）还直接被截掉。现在先按脚本切成四份：

    materials  原料与规格   「Materials」节、有供应商 / 纯度 / 分子量的段
    synthesis  合成步骤     「Synthesis of X」「Preparation of Y」每一节单独一份（逐流程）
    methods    表征与测试   「Characterization」「… Test」节、仪器条件段
    figures    图表要点     Figure S1 / Table S1 的题注（表带表体）+ 补充讨论

切法全是规则（T0）：SI 的版式稳定 —— 短行当标题、目录先列一遍标题、题注以 Figure S 开头。
认不出标题的 SI（只有题注的那种）退到按段落特征分。切错的代价只是那一栏材料少一点，
模型仍只许照搬（提示词铁律），不会编。

对外：slice(md) → {'materials': [(标题, 正文)], 'synthesis': [...], 'methods': [...], 'figures': [...], 'other': [...]}
每份都是块列表：一块 ≤ _CHUNK 字符、对应一次模型调用；合成按节分块（逐流程），其余按长度分块。
"""
import re

from tools.deepread.si_filter import classify, _INSTR_PAT, _QUANT_PAT

# 标题：短、不以句号结尾、不是题注、词数不多。MineRU 常把 SI 的节名当普通段落吐出来（没有 #）。
_CAP_RE = re.compile(r'^\s*(?:Supplementary\s+)?(Figure|Fig\.?|Scheme|Table|Movie|Video|Note)\s*S?\d+', re.I | re.M)
_IMG_RE = re.compile(r'^\s*!\[[^\]]*\]\([^)]*\)\s*$', re.M)          # MineRU 的图片行，没有文字价值
_TOC_RE = re.compile(r'\s\d{1,3}\s*$')                                     # 目录行：尾巴是页码
_NOT_HEAD = re.compile(r'@|\bauthors?\b|e-?mail|corresponding|university|institute|department|laboratory|college|'
                       r'\bdoi\b|published|copyright|©|\*', re.I)
_HEAD_MAX = 100
_CHUNK = 6000                                                                # 一次调用最多喂这么多字符的合成文字
_HEAD_WORDS = 14
_KIND_RE = {
    'materials': re.compile(r'\b(materials?|chemicals?|reagents?)\b', re.I),
    'synthesis': re.compile(r'\b(synthes[ie]s|preparation|prepar(?:ing|e)|fabrication|fabricat(?:ing|e)|procedure|protocol|'
                            r'polymeri[sz]ation|processing|formulation|assembly|route)\b', re.I),
    'methods':   re.compile(r'\b(characteri[sz]ation|measurements?|instruments?|tests?|testing|analys[ie]s|methods?|'
                            r'experimental|calculation|simulation|validation|determination|assessment|evaluation|'
                            r'spectroscopy|microscopy|rheolog\w*|mechanical|thermal|dsc|tga|nmr|ftir|saxs|xrd)\b', re.I),
}
_SKIP_HEAD = re.compile(r'^\s*(supporting information|supplementary (information|material|data)|table of contents|contents|'
                        r'references?|supplementary references|bibliography|author\w*|acknowledg\w*|abstract|'
                        r'notes? and references)\s*:?\s*$', re.I)
_SUPPLIER_RE = re.compile(r'\b(purchased|obtained|supplied|provided) (from|by)|sigma|aldrich|used (as received|without)|'
                          r'\bMw\b|\bMn\b|molecular weight|purity|\d+\s*%\s*purity', re.I)
_ACTION_RE = re.compile(r'\b(was|were) (added|dissolved|stirred|mixed|heated|cooled|poured|cast|cured|dried|washed|'
                        r'precipitated|filtered|charged|degassed|reacted|placed|kept|allowed)\b|\bunder (nitrogen|argon|vacuum)\b', re.I)
_SYN_VERB = re.compile(r'\b(was|were) (added|dissolved|stirred|mixed|poured|cast|precipitated|charged)\b', re.I)
_PIPE_RE = re.compile(r'^\s*\|.*\|\s*$', re.M)


def _paras(md):
    return [p.strip() for p in re.split(r'\n\s*\n', md or '') if p.strip()]


def is_heading(p):
    """一段是不是节标题。`#` 开头一定是；否则要短、不以句号结尾、不是题注、不像表格行。"""
    if p.startswith('#'):
        return not _NOT_HEAD.search(p.lstrip('# '))
    if len(p) > _HEAD_MAX or '\n' in p or ' | ' in p or _CAP_RE.match(p) or _PIPE_RE.match(p) or _NOT_HEAD.search(p):
        return False
    if p.endswith(('.', ':', ';', ',')) and not p.endswith('etc.'):
        return False
    words = p.split()
    if not words or len(words) > _HEAD_WORDS:
        return False
    if sum(ch.isdigit() for ch in p) > 4:            # 「2.5 g of X」不是标题；「Synthesis of CEPU1」可以
        return False
    return bool(re.search(r'[A-Za-z]{3,}', p))


def head_kind(h):
    """标题属于哪一份材料。恰好像一种才算；两可或都不像 → ''（按段落长相分）。"""
    h = h.lstrip('#').strip()
    if _SKIP_HEAD.match(h):
        return 'skip'
    hits = [kind for kind in ('materials', 'synthesis', 'methods') if _KIND_RE[kind].search(h)]
    return hits[0] if len(hits) == 1 else ''       # 「Materials and Methods」「Material Characterization」两可 → 逐段看长相


def body_kind(p):
    """无标题时按段落长相分：题注 → figures；供应商 / 分子量 → materials；投料 + 动作 → synthesis；仪器 → methods。"""
    if _CAP_RE.search(p):
        return 'figures'
    if _SUPPLIER_RE.search(p) and not _ACTION_RE.search(p):
        return 'materials'
    if _INSTR_PAT.search(p) and not _SYN_VERB.search(p):     # 仪器段先于合成段判：「10 mg 样品以 10 °C/min 加热」是测试条件不是合成
        return 'methods'
    if _QUANT_PAT.search(p) and _ACTION_RE.search(p):
        return 'synthesis'
    if _INSTR_PAT.search(p):
        return 'methods'
    return 'other'


_META_RE = re.compile(r'@|e-?mail|corresponding author|\bdoi:|published \d|copyright|©|all rights reserved', re.I)


def _clean(p):
    """去掉图片行；只剩图片行、只有面板字母（A / B / C）、作者邮箱 DOI 之类的元信息 → 空串（丢）。"""
    p = _IMG_RE.sub('', p).strip()
    if not re.search(r'[A-Za-z]{3,}', p):
        return ''
    if len(p) < 240 and _META_RE.search(p):
        return ''
    if len(p) < 400 and _AFFIL_RE.search(p) and not _QUANT_PAT.search(p):
        return ''
    if _authors(p):
        return ''
    return p


_AFFIL_RE = re.compile(r'\b(University|Department|Institute|Laboratory|College|School of|Academy of|Center for|Centre for)\b')


def _authors(p):
    """作者名单：逗号多、几乎每个词都大写开头、没有带单位的数。"""
    if p.count(',') < 3 or _QUANT_PAT.search(p):
        return False
    words = [w for w in re.findall(r'[A-Za-z][A-Za-z\-\.]*', p) if len(w) > 1]
    return bool(words) and sum(w[0].isupper() for w in words) / len(words) >= 0.8


def _pieces(t):
    """切块用的段落：空行分段；一段超过 _CHUNK 的（MineRU 有时整节只用单换行）再按行拆。"""
    out = []
    for p in _paras(t):
        if len(p) <= _CHUNK:
            out.append(p)
        else:
            out.extend(x.strip() for x in p.split('\n') if x.strip())
    return out


def _is_toc(p):
    """目录行：短、尾巴是页码。题注在目录里也会带页码，一起丢（正文里还有一份）。"""
    return len(p) <= 160 and '\n' not in p and bool(_TOC_RE.search(p)) and not _PIPE_RE.match(p)


def sections(md):
    """[(标题, [段落])]。目录里的标题（后面紧跟另一个标题、没有正文）不算节。开头没标题的段落归到 ('', [...])。"""
    kept = [_clean(p) for kind, p in classify(md) if kind != 'drop']
    kept = [p for p in kept if p and not _is_toc(p)]
    out, cur_h, cur_b = [], '', []
    for p in kept:
        if is_heading(p):
            if cur_b or not out and cur_h == '':
                out.append((cur_h, cur_b))
            cur_h, cur_b = p.lstrip('#').strip(), []
        else:
            cur_b.append(p)
    out.append((cur_h, cur_b))
    return [(h, b) for h, b in out if b]


def slice(md):
    """SI 全文 → 四份材料。合成按节返回列表（逐流程各调一次）；其余拼成一份字符串。"""
    mat, syn, met, figs, other = [], [], [], [], []
    secs = sections(md)
    for h, body in secs:
        kind = head_kind(h) if h else ''
        if kind == 'skip':
            continue
        if kind == 'synthesis':
            text = '\n\n'.join(p for p in body if not (_CAP_RE.search(p) or _is_table(p)))
            caps = [p for p in body if _CAP_RE.search(p) or _is_table(p)]
            if text.strip():
                syn.append((h, text))
            figs.extend(caps)
            continue
        for p in body:
            k = kind or body_kind(p)
            if _CAP_RE.search(p) or _is_table(p):
                k = 'figures'
            if k == 'materials':
                mat.append(p)
            elif k == 'synthesis':
                syn.append((h, p))
            elif k == 'methods':
                met.append(p)
            elif k == 'figures':
                figs.append(p)
            else:
                other.append(p)
    # 表的表体紧跟题注：题注后面那段是表就并进题注（表体本身那条去掉）；目录里列过的题注正文里还有一份，去重
    figs = _dedupe(_attach_tables(figs, md))
    # 无标题时 synthesis 是散段：同一个（空）标题下合并成一节；太长的节按段落切成 ≤ _CHUNK 的块
    return {'materials': _chunk([('', '\n\n'.join(_dedupe(mat)))]) if mat else [],
            'synthesis': _pack(_chunk(_merge_headless(syn))),
            'methods': _chunk([('', '\n\n'.join(_dedupe(met)))]) if met else [],
            'figures': _chunk([('', '\n\n'.join(figs))]) if figs else [],
            'other': _chunk([('', '\n\n'.join(_dedupe(other)))]) if other else []}


def _dedupe(items):
    out, seen = [], set()
    for p in items:
        k = ' '.join(p.split()).lower()[:120]
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def _chunk(syn):
    out = []
    for h, t in syn:
        if len(t) <= _CHUNK:
            out.append((h, t))
            continue
        buf, n, k = [], 0, 0
        for p in _pieces(t):
            if buf and n + len(p) > _CHUNK:
                k += 1
                out.append((h + ('' if k == 1 else '（续 %d）' % k), '\n\n'.join(buf)))
                buf, n = [], 0
            buf.append(p[:_CHUNK])
            n += len(p)
        if buf:
            k += 1
            out.append((h + ('' if k == 1 else '（续 %d）' % k), '\n\n'.join(buf)))
    return out


def _is_table(p):
    return p.lstrip().startswith('<table') or bool(_PIPE_RE.match(p)) or (' | ' in p and '\n' in p)


def _pack(blocks):
    """相邻的小节合并成一块（≤ _CHUNK），小标题写进正文（「## 标题」）—— 三个 600 字的合成节不值得三次调用。"""
    out, buf, n = [], [], 0
    for h, t in blocks:
        piece = ('## %s\n%s' % (h, t)) if h else t
        if buf and n + len(piece) > _CHUNK:
            out.append(('', '\n\n'.join(buf)))
            buf, n = [], 0
        buf.append(piece)
        n += len(piece)
    if buf:
        out.append(('', '\n\n'.join(buf)))
    return out


def _attach_tables(caps, md):
    paras = _paras(md)
    idx = {p: i for i, p in enumerate(paras)}
    out, used = [], set()
    for c in caps:
        i = idx.get(c)
        if i is not None and c.lower().lstrip().startswith(('table', 'supplementary table')):
            nxt = paras[i + 1] if i + 1 < len(paras) else ''
            if _is_table(nxt):
                c = c + '\n' + nxt
                used.add(nxt)
        out.append(c)
    return [c for c in out if c not in used]


def _merge_headless(syn):
    out, loose = [], []
    for h, t in syn:
        if h:
            out.append((h, t))
        else:
            loose.append(t)
    if loose:
        out.append(('', '\n\n'.join(loose)))
    return out


def stats(md):
    return {k: [(h[:40], len(t)) for h, t in v] for k, v in slice(md).items()}
