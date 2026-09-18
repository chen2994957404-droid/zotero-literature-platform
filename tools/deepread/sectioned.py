# -*- coding: utf-8 -*-
"""分段生成的正文精读（2026-09-14，`main@v3`）：一栏一次调用，骨架由脚本拼。

**为什么从一次调用改成十几次**：老路是把 3–6 万字英文一口气喂进去、要它一口气吐
一万多字中文。云端大模型扛得住，本地小模型在这种长活上最容易乱 —— 漏图、串栏目、
后半段胡编。拆成小活之后每次几千字进、几百字出，7B 级模型也稳；而且
**栏目顺序、【图N】齐不齐、数字对不对全由脚本硬性把关，不合格只重跑那一栏。**

范式的每个数字来自 `docs/reference/精读范式_实测.md`（94 篇真实推送量出来的）。

脚本替模型兜住的事（每条都是真跑里看到的问题）：
    术语表     先从原文抽「全称（缩写）」和样品编号，塞给每一次调用 —— 十几次调用各叫各的名
    表格       合成配比、样品编号几乎全在表里，实验栏要看表，不只看文字
    图的段落   认「Figures 3 and 4」「Fig. 3a–c」这类写法，不只认单个「Fig. N」
    格式硬修   🌿🍁☘️ 用错栏、「图 1」多空格、漏 Question 前缀、混进列表 —— 正则一行的事不劳模型
    数字回查   查出原文没有的数，带着「这几个数原文没有」把那一栏重生成一次
    缩写介绍   原文「全称 (缩写)」介绍过的，实验/导读栏首次出现必须带上；缩写保持缩写、不强行译中文（用户 2026-09-18 定）
    术语表     范文里挖出的缩写→中文（data/serving/glossary.json）只作参考塞进调用；写了错的中文名才重写（票≥5 且无歧义）
    清单先行   生成前把这栏材料里带单位的数列成清单塞进提示词，生成后查覆盖，漏的点名补（2026-09-17）
    分栏缓存   每栏产出落盘；断了从断处接，改一栏提示词只重跑那一栏
    篇幅       深解段长度由图数算：图多每段自动压短，全篇稳在范文的量级

流程（顺序即数据流）：
    骨架(outline) → 术语表 → 导读+引言 → 实验+Q1 → 逐图两段 → Q2+总之+通俗理解+标题
    → 脚本拼装（【图N】由脚本放）→ 统计

对外接口：
    compose(md, si_md, figs, meta, chat, log, model, local, cache)  → (content, stats)
    number_crops(figs, outline)                → [(裁图序号, 图号)]
    is_review_doc(title, outline)              → 这篇按综述写不写
    unverified_numbers(content, source)        → 精读里在原文找不到的数
    glossary(md)                               → 术语表文本
    normalize(kind, text)                      → 格式硬修后的文本
"""
import io
import json
import os
import re

from shared.domain.schema import is_review
from shared.domain.schema import outline as _ol
from shared.kernel import prompts
from shared.domain import glossary as _gl
from shared.domain import numcheck as _nums

# v2（2026-09-15）：金标三轮实测我们的汉字数中位 5900、范文（774 篇）中位 3872，篇幅比 1.75 ——
# 各栏一起收：导读 300–400、引言 2 段、实验各段封顶、索引段 80–120、Q2 300–450、总之 250–330。
# v3（2026-09-15 读了高分/低分各一篇之后）：讲图数值一个不落（40 篇里数字覆盖是最弱项，漏的全是图上的数）；
# 实验步骤必须写到目标材料制成（高分那篇也在中间体合成处就停了）。
PROMPTS = {'lead': 'lead@v2', 'exp': 'exp@v3', 'fig': 'fig@v3', 'wrap': 'wrap@v2'}

# 每栏喂给模型的材料上限（字符）。够用就好：导读只要摘要 + 引言 + 结论，
# 讲一张图只要它的图注 + 提到它的段落。上限是防 MineRU 吐出的巨型垃圾。
CAP_INTRO, CAP_CONCL, CAP_EXP, CAP_SI, CAP_FIG, CAP_BODY, CAP_TABLES = 12000, 4000, 10000, 16000, 7000, 12000, 6000
# 深解段总预算（字）：范文全篇中位 7000，讨论占一半以上；按图数均分，单段夹在 250–450 之间。
# 2026-09-15 金标第一轮（10 篇本地）篇幅比中位 1.74，超了 1.5 的上限 → 总预算 3600 收到 3000、单段上限 550 收到 450。
DEEP_BUDGET, DEEP_MIN, DEEP_MAX = 2400, 200, 380
# 清单先行：一栏漏掉超过这个比例的清单数才重写（全写进去不现实：实验栏几百字装不下 SI 里的几十个投料量）。
# 图那栏清单短、每个数都要；实验栏清单长、容忍一点。
MISS_TOL, MUST_CAP_FIG, MUST_CAP_EXP = 0.2, 30, 30

_Q1 = '各组分的作用是？'
_Q1_REVIEW = '各类材料体系/结构单元分别起什么作用？'
_Q2 = '本论文中所制备的材料为何性能优异？'
_TAG = re.compile(r'【(导读|引言|实验|Q1|Q2|总之|通俗理解|标题)】')
_CJK = re.compile(r'[一-鿿]')


# ── 材料切片 ─────────────────────────────────────────────────────────

def _by_kind(md, outline, kinds, cap):
    """把某几类的节按原文顺序拼起来（不连子节，避免重复），截到 cap。"""
    out, used = [], 0
    for s in outline.get('sections') or []:
        if s['kind'] in kinds:
            t = _ol.section_text(md, outline, s['id'], with_subsections=False)
            if t.strip():
                out.append(t.strip())
                used += len(t)
                if used >= cap:
                    break
    return '\n\n'.join(out)[:cap]


def _tables(md, outline, cap=CAP_TABLES, kinds=None):
    """正文里的表（MineRU 的 HTML 原样）。`kinds` 限定所在节的类别，不限就全要。"""
    out, used = [], 0
    for t in outline.get('tables') or []:
        if kinds and t.get('section') not in kinds:
            continue
        html = _ol.section_text(md, outline, t['id'])
        if not html.strip():
            continue
        block = ('【%s】%s\n%s' % (t.get('ref') or t['id'], t.get('caption') or '', html)).strip()
        out.append(block[:3000])
        used += len(out[-1])
        if used >= cap:
            break
    return '\n\n'.join(out)[:cap]


# 只登综述的刊（刊名里没有 review 字样的那些）。标题看不出来时靠它。
_REVIEW_JOURNALS = ('chem. rev', 'chemical review', 'chem. soc. rev', 'chemical society review',
                    'prog. polym', 'progress in polymer', 'prog. mater', 'progress in materials',
                    'acc. chem', 'accounts of chemical', 'nat. rev', 'nature reviews',
                    'mater. sci. eng. r', 'materials science and engineering: r', 'adv. colloid interface',
                    'polym. rev', 'polymer reviews', 'macromol. rapid', 'chem soc rev', 'chem rev')


def is_review_doc(title, outline, journal=''):
    """按综述的写法来写吗：标题像综述、刊物只登综述、或者全篇没有合成/方法节。"""
    if is_review({'title': title or ''}):
        return True
    if any(j in (journal or '').lower() for j in _REVIEW_JOURNALS):
        return True
    kinds = {s['kind'] for s in outline.get('sections') or []}
    return not (kinds & {_ol.SYNTHESIS, _ol.METHODS}) and outline.get('stats', {}).get('n_figures', 0) >= 8


# 全称里允许带一层括号：poly(vinylidene difluoride) (PVDF)、bis(trifluoromethanesulfonyl)imide (TFSI) 这类常见写法（2026-09-18）
_ABBR = re.compile(r'((?:[A-Za-z][A-Za-z0-9\-,\'’]*(?:\([A-Za-z0-9\-, ]+\)[A-Za-z0-9\-]*)?\s+){1,8})\(([A-Z][A-Za-z0-9\-]{1,14})\)')
_CODE = re.compile(r'\b[A-Z]{2,}[A-Za-z0-9]*(?:-[A-Za-z0-9]+){1,3}\b')


def _long_form(before, ab):
    """缩写前面那串词里，哪一段是它的全称（Schwartz–Hearst 的倒推法）。

    从缩写最后一个字母往前配：每个字母都要在前文里出现，第一个字母必须落在词首。
    `polyborosiloxane (PBS)` → 只取 1 个词；`lithium bis(...)imide (LiTFSI)` → 取整串。
    配不上返回空串。
    """
    s = before.rstrip()
    i, j = len(s) - 1, len(ab) - 1
    while j >= 0:
        c = ab[j].lower()
        if not c.isalnum():
            j -= 1
            continue
        while i >= 0 and (s[i].lower() != c or (j == 0 and i > 0 and s[i - 1].isalnum())):
            i -= 1
        if i < 0:
            return ''
        i -= 1
        j -= 1
    return s[i + 1:].strip(' ,')


_GLOSSARY = {'loaded': False, 'table': {}}


def domain_glossary():
    """领域术语表（缩写 → 中文），没建过就是空表：一切照旧，只是不校验译名。"""
    if not _GLOSSARY['loaded']:
        _GLOSSARY['loaded'] = True
        try:
            from shared.kernel import paths as _p
            _GLOSSARY['table'] = json.load(io.open(_p.glossary(), encoding='utf-8'))
        except (OSError, ValueError):
            _GLOSSARY['table'] = {}
    return _GLOSSARY['table']


def intro_pairs(md, limit=30):
    """原文里介绍过的缩写：[(缩写, 全称)]，按首次出现顺序。「全称 (缩写)」写法。"""
    text = _ol.scan.clean_body(md or '')
    pairs, seen = [], set()
    for m in _ABBR.finditer(text):
        ab = m.group(2)
        full = _long_form(m.group(1), ab)
        if ab in seen or len(ab) < 2 or len(full) < 4 or full.lower().startswith(('fig', 'table', 'eq')):
            continue
        seen.add(ab)
        pairs.append((ab, full))
        if len(pairs) >= limit:
            break
    return pairs


def missing_intros(text, pairs):
    """产出里用到了、但没带上原文介绍的缩写 → [(缩写, 全称)]。

    用户 2026-09-18 定的规矩：**缩写保持缩写，不强行译成中文**；但原文介绍过的（「全称 (缩写)」），
    首次出现时要把介绍带过来，不许遗漏。「带过来」认三种写法：英文全称原样、「中文名（缩写）」、「缩写（全称）」。
    """
    out = []
    for ab, full in pairs or []:
        if not re.search(r'(?<![A-Za-z0-9])%s(?![A-Za-z0-9])' % re.escape(ab), text or ''):
            continue                                   # 这栏根本没用到它
        introduced = (full.lower() in (text or '').lower()
                      or re.search(r'[\u4e00-\u9fff][\u4e00-\u9fff\d\-]{1,14}[（(]%s[)）]' % re.escape(ab), text or '')
                      or re.search(r'%s\s*[（(][^（()）]{4,}[)）]' % re.escape(ab), text or ''))
        if not introduced:
            out.append((ab, full))
    return out


def glossary(md, limit=30):
    """从原文抽术语表：「全称（缩写）」对 + 出现 ≥3 次的样品编号（PDMS-IU-12 这种）。

    塞给每一次调用，十几次调用才会用同一套名字。**只抽不译**：缩写保持缩写，不强行给中文；
    原文介绍过的，首次出现带上介绍（`missing_intros` 会查）。领域术语表只作参考。
    """
    text = _ol.scan.clean_body(md or '')
    ip = intro_pairs(md, limit)
    pairs = ['%s = %s' % (ab, full) for ab, full in ip]
    seen = {ab for ab, _ in ip}
    counts = {}
    for m in _CODE.finditer(text):
        c = m.group(0)
        if c not in seen and not c.startswith(('DOI', 'ISSN', 'HTTP')):
            counts[c] = counts.get(c, 0) + 1
    codes = [c for c, n in sorted(counts.items(), key=lambda x: -x[1]) if n >= 3][:20]
    lines = []
    if pairs:
        lines.append('原文介绍过的缩写（缩写保持缩写，不必硬译；首次出现时按原文带上介绍，写成「全称 (缩写)」或「中文名 (缩写)」，'
                     '原文没介绍的只写缩写）：' + '；'.join(pairs))
    if codes:
        lines.append('样品/体系编号（原样使用，不许改写）：' + '、'.join(codes))
    tr = _gl.prompt_block(domain_glossary(), text)
    if tr:
        lines.append(tr)
    return '\n'.join(lines)


def _mentions(block, num):
    """这段文字提到第 num 张图吗。认「Fig. 3」「Figures 3 and 4」「Figs. 3–5」「Fig. 3a–c」。"""
    for m in re.finditer(r'\b(?:Fig(?:ure)?s?\.?|Scheme)\s*((?:S?\d+[a-z]?(?:\s*[–\-‒]\s*S?\d*[a-z]?)?\s*(?:,|and|&)?\s*)+)',
                         block, re.I):
        for tok in re.split(r'\s*(?:,|and|&)\s*', m.group(1)):
            tok = tok.strip()
            if not tok or tok.upper().startswith('S'):
                continue
            r = re.match(r'(\d+)[a-z]?(?:\s*[–\-‒]\s*(\d+)?[a-z]?)?', tok)
            if not r:
                continue
            a = int(r.group(1))
            b = int(r.group(2)) if r.group(2) else a
            if a <= num <= b:
                return True
    return False


def _fig_context(md, outline, num, cap=CAP_FIG):
    """讨论第 num 张图的材料：完整图注 + 正文里提到它的段落（非正文节除外）+ 那些段落里引到的表。"""
    text = _ol.scan.clean_body(md or '')
    cap_txt = ''
    for f in outline.get('figures') or []:
        if re.search(r'\b%d\b' % num, f['ref']):
            cap_txt = _ol.section_text(md, outline, f['id'])
            break
    nonbody = [(s['start'], s['end']) for s in outline.get('sections') or []
               if s['kind'] == _ol.NONBODY]
    paras, pos, tabs = [], 0, set()
    for block in re.split(r'(\n\s*\n)', text):
        if block.strip() and _mentions(block, num) and not _ol._FIGCAP_RE.match(block):
            if not any(a <= pos < b for a, b in nonbody):
                paras.append(block.strip())
                tabs.update(int(x) for x in re.findall(r'\bTable\s*(\d+)', block, re.I))
        pos += len(block)
    body = '\n\n'.join(paras)[:cap]
    tab_txt = ''
    if tabs:
        want = [t['id'] for t in outline.get('tables') or []
                if any(re.search(r'\b%d\b' % n, t.get('ref') or '') for n in tabs)]
        tab_txt = '\n\n'.join(_ol.section_text(md, outline, tid)[:2500] for tid in want[:2])
    return cap_txt.strip(), body, tab_txt


# ── 格式硬修 ─────────────────────────────────────────────────────────

def _strip_md(p):
    p = re.sub(r'^\s*(?:[-*•]\s+|#+\s*|\d+[.、]\s+)', '', p)
    return p.replace('**', '').strip()


def normalize(kind, text):
    """把模型常犯的格式错顺手修掉；修不了的原样返回，由调用方判是否重跑。

    kind: lead / intro / exp / q1 / fig_idx / fig_deep / q2 / summary / plain / title
    """
    t = _strip_md(text or '')
    t = re.sub(r'图\s+(\d)', r'图\1', t)
    t = re.sub(r'▲\s*图', '▲图', t)
    if kind == 'q1':
        t = t.replace('🌿', '🍁').replace('☘️', '🍁').replace('☘', '🍁')
        if not t.startswith('Question'):
            t = 'Question：' + t.lstrip('：: ')
        t = re.sub(r'^Question\s*[:：]\s*', 'Question：', t)
    elif kind == 'q2':
        t = t.replace('🌿', '☘️').replace('🍁', '☘️')
        if not t.startswith('Question'):
            t = 'Question：' + t.lstrip('：: ')
        t = re.sub(r'^Question\s*[:：]\s*', 'Question：', t)
    elif kind == 'exp':
        t = re.sub(r'^[（(]\s*(\d)\s*[）)]', r'（\1）', t)
        if t.startswith('（2）'):
            t = t.replace('🍁', '🌿').replace('☘️', '🌿').replace('☘', '🌿')
    elif kind == 'summary':
        t = re.sub(r'^(总之|总而言之|综上所述)[，,：:]?\s*', '', t)
        t = '总之，' + t
    elif kind == 'plain':
        t = re.sub(r'^通俗(理解|地说|来说)?\s*[:：]?\s*', '', t)
        t = '通俗理解：' + t
    elif kind == 'title':
        t = t.splitlines()[0] if t else ''
        t = t.strip('「」“”" ')
    return t.strip()


_PAREN = re.compile(r'（[^（）]*）|\([^()]*\)')


def _prose(p):
    """去掉括号里的东西再判中英：「聚甲基丙烯酸甲酯（PMMA, poly(methyl methacrylate)）」
    括号里的英文全称是范式允许的，不该被当成没翻译（2026-09-14 三篇实测里两处误报都是它）。"""
    return _PAREN.sub('', _PAREN.sub('', p or ''))


def _looks_english(p):
    """一段里汉字太少 = 模型用英文写了（本地小模型偶发），要重跑。"""
    s = re.sub(r'[\s\d\W]', '', _prose(p))
    return len(s) > 40 and len(_CJK.findall(s)) / len(s) < 0.5


# 连续拉丁字母（含空格、连字符、括号）≥ 这么长 = 一整句英文没翻。
# 缩写（LiTFSI）、化学式、样品编号都远短于此；「Fourier-transform infrared spectroscopy」这种才会中。
_LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z ,'’()\-/]{29,}[A-Za-z)]")


def untranslated(p):
    """一段里没翻译的英文长串（去掉术语表里允许原样的缩写与编号之后）。"""
    out = []
    for m in _LATIN_RUN.finditer(_prose(p)):
        run = m.group(0)
        words = [w for w in re.split(r'[\s,/()\-]+', run) if w]
        # 全是大写缩写/带数字的编号（PDMS-IU-12, LiTFSI）不算；有 ≥3 个普通小写词才算英文句
        if sum(1 for w in words if re.fullmatch(r'[a-z]{3,}', w)) >= 3:
            out.append(run.strip())
    # 汉字紧挨着一个长的小写英文词（「剪切增 stiffening」）：半句没翻。
    # 缩写（大写）、化学式、tan δ 这类短词不算；括号里的已在 _prose 里剥掉。
    for m in re.finditer(r'[一-鿿]\s?([a-z]{7,})\b', _prose(p)):
        out.append(m.group(1))
    return out


# ── 调模型 ───────────────────────────────────────────────────────────

_LOCAL = {'on': False}


def _call(chat, sysp, user, max_tokens, model=None):
    """走「精读」用途的路由（面板里配的通道）。`model` 显式给了就用它。"""
    if _LOCAL['on']:
        # 本地档：不走路由表，直接找本机 Ollama（免费、离线、答案可复现）。
        return chat(sysp, user, provider='ollama', model=model or None, temperature=0.0,
                    max_tokens=max_tokens, thinking=False)
    return chat(sysp, user, purpose='DEEPREAD', model=model, temperature=0.3,
                max_tokens=max_tokens, thinking=False)


def _parse_tagged(text):
    """`【导读】…【引言】…` → {'导读': '…', '引言': '…'}。标记缺了就缺，调用方判。"""
    text = re.sub(r'<think>[\s\S]*?</think>', '', text or '')
    out, parts = {}, _TAG.split(text)
    for i in range(1, len(parts) - 1, 2):
        out[parts[i]] = parts[i + 1].strip()
    return out


def _paras(text):
    return [p.strip() for p in re.split(r'\n\s*\n|\n', text or '') if p.strip()]


def _sub(tpl, **kw):
    for k, v in kw.items():
        tpl = tpl.replace('{{%s}}' % k, v)
    return tpl


def _with_fix(chat, sysp, user, max_tokens, model, parse, ok, source, log, what, must=None, intros=None):
    """调一栏：合形检查 → 中文检查 → 数字回查 → 漏数检查 → 不合格带着原因重来（最多三次）。

    `parse(raw) -> dict`，`ok(d) -> bool`。数字回查对 dict 里所有字符串值做。
    `must` 是这栏材料里的数值清单（`numbers.must_numbers`）：漏得多（超过 MISS_TOL）就点名补。
    三次都不干净就把最后一稿交出去 —— 拼装那头还有统计，不在这里死磕。
    """
    note, best, d = '', None, {}
    for attempt in (1, 2, 3):
        d = parse(_call(chat, sysp, user + note, max_tokens, model) or '')
        if not ok(d):
            log('  %s第 %d 次输出不合形，重试' % (what, attempt))
            note = '\n\n⚠ 上一稿格式不对（缺栏目或不是要求的段落形状），严格按输出格式重写。'
            continue
        texts = [v for k, v in d.items() if isinstance(v, str) and not k.startswith('_')]
        if any(_looks_english(p) for p in texts):
            log('  %s第 %d 次有英文段，重试' % (what, attempt))
            note, best = '\n\n⚠ 上一稿有整段英文，全部用中文重写。', d
            continue
        runs = [r for p in texts for r in untranslated(p)]
        if runs and attempt < 3:
            log('  %s第 %d 次有没翻的英文「%s…」，重写' % (what, attempt, runs[0][:30]))
            note = ('\n\n⚠ 上一稿里这些英文没有翻译：%s。把英文全称译成中文，括号里保留缩写；'
                    '其余内容保持不变，按同样格式重写。' % '；'.join(r[:60] for r in runs[:5]))
            best = d
            continue
        lost = missing_intros('\n'.join(texts), intros or [])
        if lost and attempt < 3:
            log('  %s第 %d 次漏了原文对缩写的介绍：%s，补写' % (what, attempt, '、'.join(ab for ab, _ in lost[:4])))
            note = ('\n\n⚠ 上一稿这些缩写原文有介绍，首次出现时要带上（写成「全称 (缩写)」或「中文名 (缩写)」）：%s。'
                    '其余内容保持不变，按同样格式重写。' % '；'.join('%s = %s' % (ab, full) for ab, full in lost[:8]))
            best = d
            continue
        wrong = _gl.mismatches(domain_glossary(), '\n'.join(texts))
        if wrong and attempt < 3:
            log('  %s第 %d 次译名错：%s，重写' % (what, attempt, '、'.join('%s→%s' % (en, ok) for en, _, ok in wrong[:4])))
            note = ('\n\n⚠ 上一稿这些缩写的中文名写错了：%s。改成给定的译名，其余内容保持不变，按同样格式重写。'
                    % '；'.join('%s 应为「%s」（你写成了「%s」）' % (en, ok, zh) for en, zh, ok in wrong[:8]))
            best = d
            continue
        bad = unverified_numbers('\n'.join(texts), source)
        if bad and attempt < 3:
            log('  %s第 %d 次有原文没有的数 %s，重写' % (what, attempt, '、'.join(bad[:6])))
            note = ('\n\n⚠ 上一稿里这些数在原文里找不到：%s。删掉它们或改成原文的说法，'
                    '其余内容保持不变，按同样格式重写。' % '、'.join(bad[:10]))
            best = d
            continue
        miss = _nums.missing_numbers('\n'.join(texts), must or [])
        if must and attempt < 3 and len(miss) > MISS_TOL * len(must):
            log('  %s第 %d 次漏了 %d/%d 个数（%s…），补写' % (what, attempt, len(miss), len(must), '、'.join(miss[:4])))
            note = ('\n\n⚠ 上一稿漏了材料里的这些数：%s。把它们写进对应的句子里（带单位、带样品编号），'
                    '其余内容保持不变，按同样格式重写。' % '、'.join(miss[:15]))
            best = d
            continue
        return d
    return d if ok(d) else (best or d)


# ── 各栏 ─────────────────────────────────────────────────────────────

def _lead(chat, md, outline, meta, review, gloss, source, model, log):
    sysp = _sub(prompts.load('deepread', PROMPTS['lead']),
                DOC_VERB='综述用"系统总结了 / 系统梳理了"' if review else '研究论文用"报道了 / 开发了 / 提出了"')
    user = ('标题: %s\n作者: %s\n期刊: %s (%s)\nDOI: %s\n%s\n\n【摘要与引言】\n%s\n\n【结论】\n%s' % (
        meta.get('title', ''), meta.get('authors', ''), meta.get('journal', ''),
        meta.get('year', ''), meta.get('doi', ''), gloss,
        _by_kind(md, outline, (_ol.ABSTRACT, _ol.BACKGROUND), CAP_INTRO),
        _by_kind(md, outline, (_ol.CONCLUSION,), CAP_CONCL)))
    d = _with_fix(chat, sysp, user, 3500, model, _parse_tagged,
                  lambda d: bool(d.get('导读') and d.get('引言')), source, log, '导读/引言', intros=intro_pairs(md))
    return normalize('lead', d.get('导读', '')), [normalize('intro', p) for p in _paras(d.get('引言', ''))]


def _exp(chat, md, si_md, outline, review, gloss, source, model, log):
    if review:
        p1, p2, p3 = '本文涉及的主要材料体系包括：', '代表性制备/加工路线是：', '评价与表征方法包括：'
        mat = _by_kind(md, outline, (_ol.BODY, _ol.RESULTS, _ol.DISCUSSION, _ol.SYNTHESIS, _ol.METHODS), CAP_BODY)
    else:
        p1, p2, p3 = '主要实验药品是：', '实验步骤是：', '测试表征方法包括：'
        mat = _by_kind(md, outline, (_ol.SYNTHESIS, _ol.METHODS), CAP_EXP)
        if len(mat) < 800:        # 方法节没认出来（Nature 式全描述性标题）：退到主体
            mat = _by_kind(md, outline, (_ol.SYNTHESIS, _ol.METHODS, _ol.BODY, _ol.RESULTS), CAP_EXP)
    tabs = _tables(md, outline, kinds=(_ol.SYNTHESIS, _ol.METHODS)) or _tables(md, outline, cap=3000)
    q1 = _Q1_REVIEW if review else _Q1
    sysp = _sub(prompts.load('deepread', PROMPTS['exp']), P1=p1, P2=p2, P3=p3, Q1=q1)
    si_part = ''
    if si_md:
        si_ol = outline.get('si') or _ol.build_outline(si_md)
        si_txt = _by_kind(si_md, si_ol, (_ol.SYNTHESIS, _ol.METHODS), CAP_SI)
        if len(si_txt) < 800:
            si_txt = _ol.scan.clean_body(si_md)[:CAP_SI]
        si_tabs = _tables(si_md, si_ol, cap=3000)
        si_part = '\n\n【补充材料 SI 的实验细节】\n' + si_txt + ('\n\n【SI 里的表】\n' + si_tabs if si_tabs else '')
    user = gloss + '\n\n【正文的实验/方法部分】\n' + mat + ('\n\n【正文里的表】\n' + tabs if tabs else '') + si_part
    must = _nums.must_numbers(mat + '\n' + tabs + '\n' + si_part, cap=MUST_CAP_EXP)
    user += _nums.checklist_block(must)

    def parse(raw):
        d = _parse_tagged(raw)
        d['实验'] = '\n'.join(normalize('exp', p) for p in _paras(d.get('实验', '')))
        if d.get('Q1'):
            d['Q1'] = re.sub(r'^Question：[^🍁]*?[？?]', 'Question：' + q1,
                             normalize('q1', d['Q1']), count=1)         # 问句钉死成范式的原话
        return d

    def ok(d):
        return all(x in d['实验'] for x in ('（1）', '（2）', '（3）')) and bool(d.get('Q1'))
    d = _with_fix(chat, sysp, user, 4500, model, parse, ok, source, log, '实验/Q1', must=must, intros=intro_pairs(md))
    return _paras(d.get('实验', '')), d.get('Q1', '')


def _one_fig(chat, md, outline, num, n_figs, gloss, source, model, log):
    cap_txt, body, tabs = _fig_context(md, outline, num)
    # 综述 20 多张图时按 DEEP_MIN 也要 4000+ 字（第四轮实测篇幅比 2.27）：图超过 12 张下限再降一档
    per = max(DEEP_MIN if n_figs <= 12 else 150, min(DEEP_MAX, DEEP_BUDGET // max(1, n_figs)))
    sysp = _sub(prompts.load('deepread', PROMPTS['fig']), DEEP_LEN='约 %d 字' % per)
    user = ('这是图 %d（全文共 %d 张图）。\n%s\n\n【原文图注】\n%s\n\n【正文里讨论它的段落】\n%s%s'
            % (num, n_figs, gloss, cap_txt or '（未找到图注）',
               body or '（正文没有单独讨论这张图的段落，按图注写）',
               ('\n\n【这些段落引到的表】\n' + tabs) if tabs else ''))
    must = _nums.must_numbers(cap_txt + '\n' + body + '\n' + tabs, cap=MUST_CAP_FIG)
    user += _nums.checklist_block(must)

    def parse(raw):
        ps = [normalize('fig_idx', p) for p in _paras(re.sub(r'<think>[\s\S]*?</think>', '', raw or ''))]
        idx = next((p for p in ps if re.match(r'^图%d\b' % num, p)), '')
        deep = next((p for p in ps if p.startswith('▲图')), '')
        # 小模型讲着讲着漂到下一张图（2026-09-15 实测：图 2 的深解段里接着写「图3，标题为…」）：
        # 从下一张图的索引句处截断，截掉的那截不是这张图的。
        deep = re.split(r'\s*图(?!%d\b)\d+，标题为' % num, deep)[0].strip()
        idx = re.split(r'\s*▲图', idx)[0].strip()
        return {'idx': idx, 'deep': deep, '_ps': ps}

    d = _with_fix(chat, sysp, user, 1800, model, parse,
                  lambda d: bool(d['idx'] and d['deep']), source, log, '图 %d ' % num, must=must)
    ps = d.get('_ps') or []
    # 三次都不合形：能拿到什么用什么，别让一张图拖死整篇
    return d['idx'] or (ps[0] if ps else ''), d['deep'] or (ps[1] if len(ps) > 1 else '')


def _wrap(chat, md, outline, meta, deeps, review, gloss, source, model, log):
    sysp = _sub(prompts.load('deepread', PROMPTS['wrap']),
                Q2='<按这篇综述的中心问题拟一个问句，例如"为什么…性能差异如此巨大？">' if review else _Q2)
    user = ('标题: %s\n期刊: %s\n%s\n\n【摘要】\n%s\n\n【结论】\n%s\n\n【前面已写好的逐图深解】\n%s' % (
        meta.get('title', ''), meta.get('journal', ''), gloss,
        _by_kind(md, outline, (_ol.ABSTRACT,), 3000),
        _by_kind(md, outline, (_ol.CONCLUSION,), CAP_CONCL),
        '\n\n'.join(deeps)[:20000]))
    d = _with_fix(chat, sysp, user, 3500, model, _parse_tagged,
                  lambda d: bool(d.get('Q2') and d.get('总之')), source, log, '收尾')
    # 缺哪栏单补哪栏：小模型一次写四栏常漏一栏（4b 实测三次都没吐 Q2）。
    # 整段重来它照样漏；只要那一栏，成功率高得多，也便宜。
    for tag in ('Q2', '总之', '通俗理解', '标题'):
        if d.get(tag):
            continue
        ask = ('上面四栏里现在只要你补写【%s】这一栏，其它栏不要写。'
               '严格以「【%s】」开头，后面接内容。' % (tag, tag))
        one = _parse_tagged(_call(chat, sysp, user + '\n\n' + ask, 1500, model) or '')
        if one.get(tag):
            d[tag] = one[tag]
            log('  收尾补写了缺的【%s】' % tag)
    out = {}
    if d.get('Q2'):
        out['Q2'] = normalize('q2', d['Q2'])
        if not review:
            out['Q2'] = re.sub(r'^Question：[^☘]*?[？?]', 'Question：' + _Q2, out['Q2'], count=1)
    if d.get('总之'):
        out['总之'] = normalize('summary', d['总之'])
    if d.get('通俗理解'):
        out['通俗理解'] = normalize('plain', d['通俗理解'])
    if d.get('标题'):
        out['标题'] = normalize('title', d['标题'])
    return out


# ── 拼装与检查 ───────────────────────────────────────────────────────

def number_crops(figs, outline):
    """裁图块 → [(裁图序号, 图号)]。只保留能定下图号的块。

    裁图是按页面位置数的：一页的第一块拿到那页的图注，其余块和目录图没有图注。
    两步定号：① 图注里写着 Figure N 的直接用；② 夹在已知号之间 / 跟在最后一个已知号
    后面的无注块，按顺序补号 —— 但只补到正文图注总数为止，多出来的（目录图、示意图）不写字。
    2026-09-14 试跑：9 块里只有 5 块自带图注，Figure 6、7 的图注被 MineRU 放到了下一页。
    """
    n_md = len(outline.get('figures') or [])
    known = {}
    seen = set()
    for i, fg in enumerate(figs, 1):
        m = re.match(r'\s*(?:Figure|Fig\.?|图|Scheme)\s*(\d+)', fg.get('caption') or '', re.I)
        if m and int(m.group(1)) not in seen:
            seen.add(int(m.group(1)))
            known[i] = int(m.group(1))
    if not known:
        # 一条图注都没认出来（Wiley 的 FIGURE 大写曾让裁图全空）：按顺序一一对应。
        # 裁图比正文图注多一块时，多出来的那块当目录图，从第二块起对应。
        if n_md == 0:
            return []
        off = 1 if len(figs) == n_md + 1 else 0
        return [(i, i - off) for i in range(1 + off, min(len(figs), n_md + off) + 1)]
    out = dict(known)
    idxs = sorted(known)
    # 两个已知号之间的无注块：缺口正好装得下才补
    for a, b in zip(idxs, idxs[1:]):
        gap = list(range(a + 1, b))
        nums = list(range(known[a] + 1, known[b]))
        if gap and len(gap) == len(nums):
            out.update(zip(gap, nums))
    # 最后一个已知号之后的无注块：顺着往下补，不超过正文图注总数
    last, nxt = idxs[-1], known[idxs[-1]] + 1
    for i in range(last + 1, len(figs) + 1):
        if nxt > max(n_md, known[last]):
            break
        out[i], nxt = nxt, nxt + 1
    return sorted(out.items())


class _Cache:
    """分栏缓存：{栏名: 产出}。指纹（提示词版本 + 模型 + 本地档）变了整个作废。"""

    def __init__(self, path, fingerprint):
        self.path, self.fp, self.d = path, fingerprint, {}
        if path and os.path.exists(path):
            try:
                raw = json.load(io.open(path, encoding='utf-8'))
                if raw.get('fingerprint') == fingerprint:
                    self.d = raw.get('parts') or {}
            except (OSError, ValueError):
                pass

    def get(self, k):
        return self.d.get(k)

    def put(self, k, v):
        self.d[k] = v
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            io.open(self.path, 'w', encoding='utf-8').write(
                json.dumps({'fingerprint': self.fp, 'parts': self.d}, ensure_ascii=False, indent=1))
        except OSError:
            pass


def compose(md, si_md, figs, meta, chat, log=print, model=None, local=False, cache=None):
    """一篇 → (精读 markdown 内容, 统计)。`figs` 是裁图结果（只用它的张数与顺序），
    `meta` 是 title/authors/journal/year/doi，`chat` 是 llm_client.chat 或假替身。
    `local=True` 全部调用走本机 Ollama（温度 0，答案可复现），不花一分钱。
    `cache` 是分栏缓存文件路径：断了从断处接；改了哪栏的提示词只重跑哪栏。
    """
    _LOCAL['on'] = bool(local)
    outline = _ol.build_outline(md, si_md=si_md)
    review = is_review_doc(meta.get('title', ''), outline, meta.get('journal', ''))
    gloss = glossary(md)
    source = (md or '') + '\n' + (si_md or '')
    # 指纹里带上篇幅参数：2026-09-15 第二轮评测把深解预算收紧了，缓存却按旧参数原样复用，
    # 10 篇里 8 篇分数一字不差 —— 改了参数看不到效果比没缓存更糟。
    # 指纹里也带上术语表的版本（建表时间 + 词数）：2026-09-18 金标 v7 十篇分数与 v6 一字不差 ——
    # 术语表塞进了提示词，缓存却按旧指纹原样复用，等于什么都没跑。
    gt = domain_glossary()
    fp = '%s|%s|%s|deep=%d-%d-%d|must=%d-%d-%s|gloss=%s-%d' % ('|'.join('%s=%s' % kv for kv in sorted(PROMPTS.items())),
                                     model or '', 'local' if local else 'route',
                                     DEEP_BUDGET, DEEP_MIN, DEEP_MAX,
                                     MUST_CAP_FIG, MUST_CAP_EXP, MISS_TOL,
                                     gt.get('_built', ''), len(gt))
    C = _Cache(cache, fp)
    n_figs = len(figs)
    log('  按%s写；%d 张图；骨架 %d 节；术语 %d 条%s' % (
        '综述' if review else '研究论文', n_figs, len(outline.get('sections') or []),
        gloss.count(' = ') + gloss.count('、'), '；有缓存 %d 栏' % len(C.d) if C.d else ''))

    part = C.get('lead')
    if not part:
        part = list(_lead(chat, md, outline, meta, review, gloss, source, model, log))
        C.put('lead', part)
    lead, intro = part[0], part[1]

    part = C.get('exp')
    if not part:
        part = list(_exp(chat, md, si_md, outline, review, gloss, source, model, log))
        C.put('exp', part)
    exp, q1 = part[0], part[1]

    numbered = number_crops(figs, outline)
    log('  %d 块裁图里 %d 块定下了图号' % (n_figs, len(numbered)))
    fig_paras, deeps = [], []
    for i, num in numbered:
        part = C.get('fig:%d' % num)
        if not part:
            part = list(_one_fig(chat, md, outline, num, len(numbered), gloss, source, model, log))
            C.put('fig:%d' % num, part)
        fig_paras.append((i, part[0], part[1]))
        if part[1]:
            deeps.append(part[1])

    tail = C.get('wrap')
    if not tail:
        tail = _wrap(chat, md, outline, meta, deeps, review, gloss, source, model, log)
        C.put('wrap', tail)

    parts = []
    if tail.get('标题'):
        parts.append('# ' + tail['标题'])
    parts += ['## 导读', lead, '## 引言'] + intro
    parts += ['## 实验'] + exp
    if q1:
        parts.append(q1)
    parts.append('## 讨论')
    for i, idx, deep in fig_paras:
        parts += ['【图%d】' % i] + [p for p in (idx, deep) if p]     # 标记号 = 裁图序号
    if tail.get('Q2'):
        parts.append(tail['Q2'])
    parts += ['## 总结', tail.get('总之', '')]
    if tail.get('通俗理解'):
        parts += ['## 通俗理解', tail['通俗理解']]
    body_end = len(parts)                      # 文献信息里的 DOI 不参与数字回查
    parts += ['## 文献信息',
              '英文标题：%s' % meta.get('title', ''),
              '作者：%s' % meta.get('authors', ''),
              '期刊：%s（%s）' % (meta.get('journal', ''), meta.get('year', '')),
              'DOI：https://doi.org/%s' % meta.get('doi', '') if meta.get('doi') else 'DOI：原文未给出']
    content = '\n\n'.join(p for p in parts if p is not None and str(p).strip())

    bad = unverified_numbers('\n'.join(str(p) for p in parts[:body_end] if p), source)
    stats = {'review': review, 'n_figs': n_figs, 'n_numbered': len(numbered), 'chars': len(content),
             'figs_two_para': sum(1 for _, i, d in fig_paras if i and d),
             'has_plain': bool(tail.get('通俗理解')), 'has_title': bool(tail.get('标题')),
             'n_unverified': len(bad), 'unverified': bad[:20]}
    log('  精读 %d 字，%d/%d 张图两段齐全，原文查不到的数 %d 个%s' % (
        stats['chars'], stats['figs_two_para'], len(numbered), len(bad),
        ('：' + '、'.join(bad[:8])) if bad else ''))
    return content, stats


# 「原文里找不到的数」的判定住在 shared.domain.numcheck（问答线也用它）；这里留个同名入口，评测与测试照旧调。
unverified_numbers = _nums.unverified_numbers
