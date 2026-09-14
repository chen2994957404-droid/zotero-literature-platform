# -*- coding: utf-8 -*-
"""分段生成的正文精读（2026-09-14，`main@v3`）：一栏一次调用，骨架由脚本拼。

**为什么从一次调用改成十几次**：老路是把 3–6 万字英文一口气喂进去、要它一口气吐
一万多字中文。云端大模型扛得住，本地小模型在这种长活上最容易乱 —— 漏图、串栏目、
后半段胡编。拆成小活之后每次几千字进、几百字出，7B 级模型也稳；而且
**栏目顺序、【图N】齐不齐、数字对不对全由脚本硬性把关，不合格只重跑那一栏。**

范式的每个数字来自 `docs/reference/精读范式_实测.md`（94 篇真实推送量出来的）。

流程（顺序即数据流）：
    骨架(outline) → 按类别切材料 → 导读+引言 → 实验+Q1 → 逐图两段 → Q2+总之+通俗理解+标题
    → 脚本拼装（【图N】由脚本放，模型不用管）→ 数字回查

对外接口：
    compose(md, si_md, figs, meta, chat, log)  → (content_markdown, stats)
    is_review_doc(title, outline)              → 这篇按综述写不写
    unverified_numbers(content, source)        → 精读里在原文找不到的数
"""
import re

from shared.domain.schema import is_review
from shared.domain.schema import outline as _ol
from shared.kernel import prompts

PROMPTS = {'lead': 'lead@v1', 'exp': 'exp@v1', 'fig': 'fig@v1', 'wrap': 'wrap@v1'}

# 每栏喂给模型的材料上限（字符）。够用就好：导读只要摘要 + 引言 + 结论，
# 讲一张图只要它的图注 + 提到它的段落。上限是防 MineRU 吐出的巨型垃圾。
CAP_INTRO, CAP_CONCL, CAP_EXP, CAP_SI, CAP_FIG, CAP_BODY = 12000, 4000, 10000, 16000, 7000, 12000
MANY_FIGS = 15            # 图超过这个数，每段深解压到 300 字上下（综述 16–31 张图也只写 9000 字）

_Q1 = '各组分的作用是？'
_Q2 = '本论文中所制备的材料为何性能优异？'
_TAG = re.compile(r'【(导读|引言|实验|Q1|Q2|总之|通俗理解|标题)】')


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


def is_review_doc(title, outline):
    """按综述的写法来写吗：标题像综述，或者全篇没有合成/方法节。"""
    if is_review({'title': title or ''}):
        return True
    kinds = {s['kind'] for s in outline.get('sections') or []}
    return not (kinds & {_ol.SYNTHESIS, _ol.METHODS}) and outline.get('stats', {}).get('n_figures', 0) >= 8


def _fig_context(md, outline, num, cap=CAP_FIG):
    """讨论第 num 张图的材料：完整图注 + 正文里提到它的段落（非正文节除外）。"""
    text = _ol.scan.clean_body(md or '')
    cap_txt = ''
    for f in outline.get('figures') or []:
        if re.search(r'\b%d\b' % num, f['ref']):
            cap_txt = _ol.section_text(md, outline, f['id'])
            break
    pat = re.compile(r'\b(?:Fig(?:ure)?s?\.?|Scheme)\s*%d(?![0-9])' % num, re.I)
    nonbody = [(s['start'], s['end']) for s in outline.get('sections') or []
               if s['kind'] == _ol.NONBODY]
    paras, pos = [], 0
    for block in re.split(r'(\n\s*\n)', text):
        if block.strip() and pat.search(block) and not _ol._FIGCAP_RE.match(block):
            if not any(a <= pos < b for a, b in nonbody):
                paras.append(block.strip())
        pos += len(block)
    body = '\n\n'.join(paras)
    return cap_txt.strip(), body[:cap]


# ── 调模型与解析 ─────────────────────────────────────────────────────

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


def _call(chat, sysp, user, max_tokens, model=None):
    """走「精读」用途的路由（面板里配的通道）。`model` 显式给了就用它。"""
    if _LOCAL['on']:
        # 本地档：不走路由表，直接找本机 Ollama（免费、离线、答案可复现）。
        # 这条是给「本地小模型能不能胜任精读」这个实验开的门，不是常规路径。
        return chat(sysp, user, provider='ollama', model=model or None, temperature=0.0,
                    max_tokens=max_tokens, thinking=False)
    return chat(sysp, user, purpose='DEEPREAD', model=model, temperature=0.3,
                max_tokens=max_tokens, thinking=False)


_LOCAL = {'on': False}


def _lead(chat, md, outline, meta, review, model, log):
    sysp = _sub(prompts.load('deepread', PROMPTS['lead']),
                DOC_VERB='综述用"系统总结了 / 系统梳理了"' if review else '研究论文用"报道了 / 开发了 / 提出了"')
    user = ('标题: %s\n作者: %s\n期刊: %s (%s)\nDOI: %s\n\n【摘要与引言】\n%s\n\n【结论】\n%s' % (
        meta.get('title', ''), meta.get('authors', ''), meta.get('journal', ''),
        meta.get('year', ''), meta.get('doi', ''),
        _by_kind(md, outline, (_ol.ABSTRACT, _ol.BACKGROUND), CAP_INTRO),
        _by_kind(md, outline, (_ol.CONCLUSION,), CAP_CONCL)))
    for attempt in (1, 2):
        d = _parse_tagged(_call(chat, sysp, user, 3500, model))
        if d.get('导读') and d.get('引言'):
            return d['导读'], _paras(d['引言'])
        log('  导读/引言第 %d 次输出缺栏目，重试' % attempt)
    return d.get('导读', ''), _paras(d.get('引言', ''))


def _exp(chat, md, si_md, outline, review, model, log):
    if review:
        p1, p2, p3 = '本文涉及的主要材料体系包括：', '代表性制备/加工路线是：', '评价与表征方法包括：'
        mat = _by_kind(md, outline, (_ol.BODY, _ol.RESULTS, _ol.DISCUSSION, _ol.SYNTHESIS, _ol.METHODS), CAP_BODY)
    else:
        p1, p2, p3 = '主要实验药品是：', '实验步骤是：', '测试表征方法包括：'
        mat = _by_kind(md, outline, (_ol.SYNTHESIS, _ol.METHODS), CAP_EXP)
        if len(mat) < 800:        # 方法节没认出来（Nature 式全描述性标题）：退到主体
            mat = _by_kind(md, outline, (_ol.SYNTHESIS, _ol.METHODS, _ol.BODY, _ol.RESULTS), CAP_EXP)
    sysp = _sub(prompts.load('deepread', PROMPTS['exp']), P1=p1, P2=p2, P3=p3,
                Q1='各类材料体系/结构单元分别起什么作用？' if review else _Q1)
    si_part = ''
    if si_md:
        si_ol = outline.get('si') or _ol.build_outline(si_md)
        si_txt = _by_kind(si_md, si_ol, (_ol.SYNTHESIS, _ol.METHODS), CAP_SI)
        if len(si_txt) < 800:
            si_txt = _ol.scan.clean_body(si_md)[:CAP_SI]
        si_part = '\n\n【补充材料 SI 的实验细节】\n' + si_txt
    user = '【正文的实验/方法部分】\n' + mat + si_part
    for attempt in (1, 2):
        d = _parse_tagged(_call(chat, sysp, user, 4500, model))
        exp = d.get('实验', '')
        if '（1）' in exp and '（2）' in exp and '（3）' in exp and d.get('Q1'):
            return _paras(exp), d['Q1']
        log('  实验/Q1 第 %d 次输出不合形，重试' % attempt)
    return _paras(d.get('实验', '')), d.get('Q1', '')


def _one_fig(chat, md, outline, num, n_figs, model, log):
    cap_txt, body = _fig_context(md, outline, num)
    sysp = _sub(prompts.load('deepread', PROMPTS['fig']),
                DEEP_LEN='300 字上下' if n_figs > MANY_FIGS else '300–600 字')
    user = ('这是图 %d（全文共 %d 张图）。\n\n【原文图注】\n%s\n\n【正文里讨论它的段落】\n%s'
            % (num, n_figs, cap_txt or '（未找到图注）', body or '（正文没有单独讨论这张图的段落，按图注写）'))
    for attempt in (1, 2):
        raw = re.sub(r'<think>[\s\S]*?</think>', '', _call(chat, sysp, user, 1800, model) or '')
        ps = _paras(raw)
        idx = next((p for p in ps if re.match(r'^图\s*%d\b' % num, p) and not p.startswith('▲')), '')
        deep = next((p for p in ps if p.startswith('▲')), '')
        if idx and deep:
            return idx, deep
        log('  图 %d 第 %d 次输出不是两段，重试' % (num, attempt))
    # 两次都不合形：能拿到什么用什么，别让一张图拖死整篇
    return (idx or (ps[0] if ps else '')), (deep or (ps[1] if len(ps) > 1 else ''))


def _wrap(chat, md, outline, meta, deeps, review, model, log):
    sysp = _sub(prompts.load('deepread', PROMPTS['wrap']),
                Q2='<按这篇综述的中心问题拟一个问句，例如"为什么…性能差异如此巨大？">' if review else _Q2)
    user = ('标题: %s\n期刊: %s\n\n【摘要】\n%s\n\n【结论】\n%s\n\n【前面已写好的逐图深解】\n%s' % (
        meta.get('title', ''), meta.get('journal', ''),
        _by_kind(md, outline, (_ol.ABSTRACT,), 3000),
        _by_kind(md, outline, (_ol.CONCLUSION,), CAP_CONCL),
        '\n\n'.join(deeps)[:20000]))
    for attempt in (1, 2):
        d = _parse_tagged(_call(chat, sysp, user, 3500, model))
        if d.get('Q2') and d.get('总之'):
            return d
        log('  收尾第 %d 次输出缺栏目，重试' % attempt)
    return d


# ── 拼装与检查 ───────────────────────────────────────────────────────

def compose(md, si_md, figs, meta, chat, log=print, model=None, local=False):
    """一篇 → (精读 markdown 内容, 统计)。`figs` 是裁图结果（只用它的张数与顺序），
    `meta` 是 title/authors/journal/year/doi，`chat` 是 llm_client.chat 或假替身。
    `local=True` 全部调用走本机 Ollama（温度 0，答案可复现），不花一分钱。
    """
    _LOCAL['on'] = bool(local)
    outline = _ol.build_outline(md, si_md=si_md)
    review = is_review_doc(meta.get('title', ''), outline)
    n_figs = len(figs)
    log('  按%s写；%d 张图；骨架 %d 节' % ('综述' if review else '研究论文', n_figs,
                                          len(outline.get('sections') or [])))

    lead, intro = _lead(chat, md, outline, meta, review, model, log)
    exp, q1 = _exp(chat, md, si_md, outline, review, model, log)
    # 裁图是按页面上的位置数的，不是按图号：目录图、一页两图的第二块都没有图注。
    # 只给**认得出图号**的写两段；其余的不写字，`insert_figures` 会把它们当补充图挂在总结前
    # （2026-09-14 试跑：9 块裁图里 2 块没图注，模型只能写「原文未给出」凑数 —— 别让它凑）。
    fig_paras, deeps, seen = [], [], set()
    numbered = []
    for i, fg in enumerate(figs, 1):
        m = re.match(r'\s*(?:Figure|Fig\.?|图|Scheme)\s*(\d+)', fg.get('caption') or '', re.I)
        if m and int(m.group(1)) not in seen:
            seen.add(int(m.group(1)))
            numbered.append((i, int(m.group(1))))
    log('  %d 块裁图里 %d 块认得出图号' % (n_figs, len(numbered)))
    for i, num in numbered:
        idx, deep = _one_fig(chat, md, outline, num, len(numbered), model, log)
        fig_paras.append((i, idx, deep))
        if deep:
            deeps.append(deep)
    tail = _wrap(chat, md, outline, meta, deeps, review, model, log)

    parts = []
    if tail.get('标题'):
        parts.append('# ' + tail['标题'].strip().splitlines()[0])
    parts += ['## 导读', lead, '## 引言'] + intro
    parts += ['## 实验'] + exp
    if q1:
        parts.append(q1 if q1.startswith('Question') else 'Question：%s%s' % (_Q1, q1))
    parts.append('## 讨论')
    for i, idx, deep in fig_paras:
        parts += ['【图%d】' % i] + [p for p in (idx, deep) if p]     # 标记号 = 裁图序号
    if tail.get('Q2'):
        parts.append(tail['Q2'])
    parts += ['## 总结', tail.get('总之', '')]
    if tail.get('通俗理解'):
        parts += ['## 通俗理解', tail['通俗理解']]
    parts += ['## 文献信息',
              '英文标题：%s' % meta.get('title', ''),
              '作者：%s' % meta.get('authors', ''),
              '期刊：%s（%s）' % (meta.get('journal', ''), meta.get('year', '')),
              'DOI：https://doi.org/%s' % meta.get('doi', '') if meta.get('doi') else 'DOI：原文未给出']
    content = '\n\n'.join(p for p in parts if p is not None and str(p).strip())

    bad = unverified_numbers(content, (md or '') + '\n' + (si_md or ''))
    stats = {'review': review, 'n_figs': n_figs, 'n_numbered': len(numbered), 'chars': len(content),
             'figs_two_para': sum(1 for _, i, d in fig_paras if i and d),
             'has_plain': bool(tail.get('通俗理解')), 'has_title': bool(tail.get('标题')),
             'n_unverified': len(bad), 'unverified': bad[:20]}
    log('  精读 %d 字，%d/%d 张图两段齐全，原文查不到的数 %d 个%s' % (
        stats['chars'], stats['figs_two_para'], len(numbered), len(bad),
        ('：' + '、'.join(bad[:8])) if bad else ''))
    return content, stats


_NUM = re.compile(r'(?<![\d.])(\d+(?:\.\d+)?)(?!\d)')


def unverified_numbers(content, source):
    """精读里出现、原文（正文+SI）里找不到的数。**只报不改**：这是给评测和人看的信号。

    过滤掉不是"数据"的数：图号/表号/第几/年份/单个位数（"3 种方法"这种）。
    源文本去掉空格与千分位逗号再比 —— MineRU 常把 `1 000` 拆开。
    """
    src = re.sub(r'[\s,]', '', source or '')
    out, seen = [], set()
    for m in _NUM.finditer(content or ''):
        s = m.group(1)
        pre = content[max(0, m.start() - 2):m.start()]
        if s in seen or re.search(r'[图表第（(]$', pre) or re.search(r'^[a-z]', content[m.end():m.end() + 1]):
            continue
        if ('.' not in s and (len(s) < 2 or (len(s) == 4 and s.startswith(('19', '20'))))):
            continue
        seen.add(s)
        if s not in src and s.rstrip('0').rstrip('.') not in src:
            out.append(s)
    return out
