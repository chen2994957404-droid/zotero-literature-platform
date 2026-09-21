# -*- coding: utf-8 -*-
"""zoning · 句子分区（2026-09-21）：先判每句话是哪种话，再决定往哪条抽取线送。

依据：Argumentative Zoning / CoreSC / MuLMS-AZ 那条线（docs/reference/本地化拆解_方法调研.md 第七节）——
论文句子按修辞功能可分区，分区是句子级封闭分类，正是小模型的形状。分完区：
    RESULT / FIGURE 句里的数 → 数值事实（问性质、问样品）
    METHOD 句里的数          → 投料 / 条件（走合成动作那条线，不问「哪项性质」）
    BACKGROUND / OTHER      → 不产单元
    CLAIM                   → 主张

六个区（比 CoreSC 粗，够用且小模型分得清）：
    1 BACKGROUND  动机、前人工作、常识背景
    2 METHOD      合成 / 制备 / 加工步骤，表征与测试手段，模拟设置
    3 RESULT      观察到 / 测到 什么（含数值）
    4 CLAIM       解释、机理、结论、比前人强在哪
    5 FIGURE      图注、图的描述
    6 OTHER       致谢、作者信息、过渡句、章节标题

省调用的两层先验（T0）：
    - 骨架已判为 合成 / 方法 的节 → 整节 METHOD，不问；背景 / 结论 节同理；图注 → FIGURE
    - 只有 主体 / 结果 / 讨论 这几类混合节、以及无标题论文，才让模型分；一次 8 句，答 8 个数字

对外接口：
    sentences(text) → [句]                          纯函数
    zone_paper(md, outline, chat, model, log) → [(句, 区, 来源)]
    zone_stats(zoned) → {区: 句数}
"""
import re

from shared.domain.schema import outline as _ol

ZONES = ('BACKGROUND', 'METHOD', 'RESULT', 'CLAIM', 'FIGURE', 'OTHER')
BATCH = 8
NUM_CTX = 3072
_ABBR = re.compile(r'\b(?:Fig|Figs|Eq|Eqs|Ref|Refs|et al|vs|approx|ca|i\.e|e\.g|No|Dr|Prof|Tab|Sec|wt|vol|mol)\.$', re.I)
_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z(\[])')

SYS = ('You classify sentences from a materials-science paper into exactly one zone each:\n'
       '1 BACKGROUND (motivation, prior work, general knowledge)\n'
       '2 METHOD (how samples were made or processed; what technique or instrument measured what; simulation setup)\n'
       '3 RESULT (what was observed or measured, including numbers)\n'
       '4 CLAIM (interpretation, mechanism, conclusion, comparison with prior work)\n'
       '5 FIGURE (a figure caption or a sentence that only says what a figure shows)\n'
       '6 OTHER (acknowledgements, author info, transitions, headings)\n'
       'Answer with the zone numbers only, one per line, in the same order as the sentences.')

_KIND_ZONE = {_ol.SYNTHESIS: 'METHOD', _ol.METHODS: 'METHOD', _ol.BACKGROUND: 'BACKGROUND',
              _ol.CONCLUSION: 'CLAIM', _ol.NONBODY: 'OTHER'}


def sentences(text):
    """段落 → 句子。按句末标点 + 大写开头切；Fig. / et al. / e.g. 这类缩写不切。"""
    out = []
    for para in re.split(r'\n\s*\n', text or ''):
        para = ' '.join(para.split())
        if not para:
            continue
        buf = ''
        for piece in _SPLIT.split(para):
            if buf and _ABBR.search(buf):
                buf += ' ' + piece
                continue
            if buf:
                out.append(buf)
            buf = piece
        if buf:
            out.append(buf)
    return [s for s in out if len(s) >= 15]


def _ask(chat, model, batch):
    user = '\n'.join('%d. %s' % (i + 1, s[:400]) for i, s in enumerate(batch))
    try:
        raw = chat(SYS, user, provider='ollama', model=model, temperature=0.0, max_tokens=8 * len(batch),
                   num_ctx=NUM_CTX, thinking=False)
    except Exception:
        return None
    nums = [int(x) for x in re.findall(r'\b([1-6])\b', raw or '')]
    if len(nums) != len(batch):
        return None
    return [ZONES[n - 1] for n in nums]


def zone_paper(md, outline, chat, model, log=print, si_md=''):
    """→ [(句, 区, 来源)]，来源 = 'kind'（骨架先验）/ 'model' / 'fallback'。"""
    out = []
    caps = [(f['start'], f['end']) for f in outline.get('figures') or []]
    n_model = n_prior = 0
    for s in outline.get('sections') or []:
        if s['kind'] == _ol.NONBODY:
            continue
        text = _ol.section_text(md, outline, s['id'], with_subsections=False)
        for a, b in caps:                                        # 图注挖出来单独算 FIGURE
            if s['start'] <= a < s['end']:
                seg = md[a:b]
                if seg in text:
                    text = text.replace(seg, '')
                    for sent in sentences(seg):
                        out.append((sent, 'FIGURE', 'kind'))
                        n_prior += 1
        sents = sentences(text)
        prior = _KIND_ZONE.get(s['kind'])
        if prior and s['kind'] != _ol.BACKGROUND:                 # 引言里也常有主张，交给模型；合成/方法/结论直接判
            out += [(x, prior, 'kind') for x in sents]
            n_prior += len(sents)
            continue
        for i in range(0, len(sents), BATCH):
            batch = sents[i:i + BATCH]
            zones = _ask(chat, model, batch)
            if zones is None:                                    # 模型没按数答：这批退回逐句问，再不行按节类兜底
                zones = []
                for x in batch:
                    z = _ask(chat, model, [x])
                    zones.append(z[0] if z else (prior or 'RESULT'))
            out += list(zip(batch, zones, ['model'] * len(batch)))
            n_model += len(batch)
    if si_md:
        for sent in sentences(si_md):
            out.append((sent, 'METHOD', 'kind'))                   # SI 按方法处理
            n_prior += 1
    log('  分区：%d 句先验、%d 句问模型' % (n_prior, n_model))
    return out


def zone_stats(zoned):
    d = {}
    for _, z, _ in zoned:
        d[z] = d.get(z, 0) + 1
    return d
