# -*- coding: utf-8 -*-
"""审稿（2026-09-19 立）：精读写完之后，让**另一个模型对着原文**逐句判，人不再抽检。

**为什么要有这一步**：分段精读里脚本能查的都查了 —— 数字在不在原文、缩写介绍了没、
栏目齐不齐。查不了的是**意思**：数对了但张冠李戴（A 样品的数说成 B 的）、原文的推测
写成定论、原文没提的机理解释、以及该讲的核心结果没讲。这三样以前靠用户抽检，
他的原话（2026-09-19）：「对于大量的数据你的抽检完全比我会好的多，应该建立 LLM 能检查的标准。」

三项检查，全部对着原文，全部机器判：
    编造 / 曲解   把一栏拆成句子，连同**写这栏时用的同一份原文材料**交给审稿模型，
                  逐句判 ok / distorted / unsupported / skip（`sectioned.*_material` 保证两边看的一样）
    数字闸（脚本）  带数的句子先让脚本核（2026-09-22）：句中有原文里找不到的数 → 直接判 unsupported，
                  不问模型；模型判「原文没有」但句中 ≥2 个数在原文同一处凑齐 → 否决成 ok。
                  换什么模型都成立的那部分活，不交给模型（规划 §十五）
    切片误判复核   被标的句子再拿**整篇原文**复核一次 —— 材料切片漏了段落不是编辑的错，
                  复核过的记成 slice_miss，那是切片器的账
    漏重点        先从摘要 + 结论 + 全部图注抽要点清单，再查精读覆盖了几条

判定：一栏有被标的句子就该重写（带着「这几句原文不支持」回炉，由 compose 的 notes 机制做）；
整篇过关 = 标出率 ≤ FLAG_TOL 且漏重点 ≤ MISS_TOL。两轮之后还过不了 → 记 needs_human，
进「待人看」清单，其余一律不经人手。

校准（`calibrate`）也不用人：拿人写的范文当「应该全过」的样本量误报率，
再往范文里**故意塞错**（改数、反转结论、加编造句）量查全率。

对外接口：
    review(content, md, si_md, chat_json, meta, log, local)  → 报告 dict
    notes_for(report)                                        → {栏: 回炉提示}（给 compose）
    passed(report)                                           → bool
    sections_of(content) / split_claims(text)                → 纯函数，测试用
    corrupt(text, seed) / html_to_content(html)              → 纯函数
    calibrate(keys, chat_json, log, tag)                     → 校准报告
"""
import io
import json
import os
import random
import re
import time

from shared.kernel import prompts
from shared.domain import numcheck as _nums
from shared.domain.schema import outline as _ol
from tools.deepread import sectioned as _sec

PROMPTS = {'claims': 'review_claims@v1', 'keypoints': 'review_keypoints@v1', 'cover': 'review_cover@v1'}
VERSION = 1
PURPOSE = 'REVIEW'

# 2026-09-20 校准（5 篇人写范文，正文+SI 都给）：干净范文本身就有 1–8% 的句子被标 —— 抽样核对多数是范文真写错了
# （热压条件数字不对、断裂功倍数写反、图 4a 的内容归到 4b）。线定在 8%：比人写的差才回炉、才进待人看。
FLAG_TOL = 0.08        # 整篇标出率（distorted + unsupported / 已判句数）超过它不过关
MISS_TOL = 2           # 漏掉的要点（missed，不含 partial）超过它不过关
BATCH = 25             # 一次交给审稿模型的句数（云端）
BATCH_LOCAL = 10       # 本地一批 10 句：25 句时 9.7B 后半批不答（2026-09-20 校准：99 句漏判 23）
CAP_SOURCE = 60000     # 整篇复核时原文截到这么多字符（云端）
# 本地档（2026-09-20 起默认）：qwen3.5 9.7B 的窗口给 24k token，材料压到 20000 字符；
# 「整篇复核」在本地退化成「前 20000 字符复核」—— 讨论段在后面的会漏，slice_miss 会偏少，校准时看这项。
CAP_LOCAL, NUM_CTX_LOCAL = 20000, 24576
CAP_CAPTIONS = 8000
MIN_CLAIM = 10         # 比这短的句子不当断言
VERDICTS = ('ok', 'distorted', 'unsupported', 'skip')
BAD = ('distorted', 'unsupported')
NO_REVIEW = ('通俗理解', '文献信息')       # 比喻不审；文献信息是脚本填的

_H2 = re.compile(r'^## (.+)$')
_FIGMARK = re.compile(r'^【图(\d+)】$')
_SPLIT = re.compile(r'(?<=[。；！？])|(?=[🌿🍁☘️])')
_CJK = re.compile(r'[一-鿿]')


# ── 拆栏、拆句（纯函数）──────────────────────────────────────────────

def sections_of(content):
    """精读 markdown → [(栏 key, 栏名, 文本)]。key 是 compose 缓存里的那套：lead / exp / fig:<标记号> / wrap。

    没有任何 `## ` 标题的文本（人写的范文）整个算一栏 'all'。
    """
    paras = [p.strip() for p in content.split('\n') if p.strip()]
    if not any(_H2.match(p) for p in paras):
        # 人写的范文：按范式起笔分栏（2026-09-22，校准第一轮误报大头之一是「整篇一栏」——引言常识没有宽容规则、材料也挑不准）
        from tools.deepread.columns import reference_sections
        secs = reference_sections(content)
        return secs or [('all', '全文', '\n'.join(p for p in paras if not p.startswith('# ')))]
    out, cur, buf = [], None, []

    def flush():
        if cur and buf:
            out.append((cur[0], cur[1], '\n'.join(buf)))
        buf.clear()

    for p in paras:
        m = _H2.match(p)
        if m:
            flush()
            name = m.group(1).strip()
            cur = ({'导读': 'lead', '引言': 'lead', '实验': 'exp', '讨论': 'fig:0',
                    '总结': 'wrap'}.get(name, 'skip' if name in NO_REVIEW else 'wrap'), name)
            continue
        fm = _FIGMARK.match(p)
        if fm:
            flush()
            cur = ('fig:%s' % fm.group(1), '图%s' % fm.group(1))
            continue
        if p.startswith('# ') or cur is None:
            continue
        if cur[0].startswith('fig:') and p.startswith('Question'):   # 讨论末尾的 Q2 归收尾栏
            flush()
            cur = ('wrap', 'Q2')
        buf.append(p)
    flush()
    # 同 key 的相邻栏合并（导读 + 引言；Q2 + 总之）
    merged = []
    for k, name, text in out:
        if k == 'skip':
            continue
        if merged and merged[-1][0] == k:
            merged[-1] = (k, merged[-1][1] + '/' + name, merged[-1][2] + '\n' + text)
        else:
            merged.append((k, name, text))
    return merged


def split_claims(text):
    """一栏文本 → 句子列表。按句号 / 分号 / 段内分隔符切，太短的丢掉，Question 前缀剥掉。"""
    out = []
    for para in text.split('\n'):
        for s in _SPLIT.split(para):
            s = s.strip(' 🌿🍁☘️\t')
            s = re.sub(r'^Question[：:]\s*', '', s)
            s = re.sub(r'^(?:第[一二三四五六七八九十]+|[（(]?\d+[）)]?)[，,、]\s*', '', s)
            if len(s) >= MIN_CLAIM and _CJK.search(s) and not s.endswith(('？', '?')) and not _DECOR.search(s):
                out.append(s)
    return out


# 公众号的小标题装饰（「⃣ 体外和体内的抗菌性能 ▼」）不是断言（2026-09-22 第六轮误报里有）
_DECOR = re.compile(r'[▼▲⃣]')

# 被标句子的四类（2026-09-22 第六轮逐条归类得出）：校准报告按类分开计，才看得出误报出在哪
_FIG_SENT = re.compile(r'^\s*(?:[A-Za-z](?:[、,，\s–-]*[A-Za-z])*\s*小?图|小图|该图|此图|图\s*\d|[（(]?[a-zA-Z][）)]\s*)')
_INFER = ('提供', '思路', '意义', '潜力', '瓶颈', '其一', '其二', '其三', '其四', '其五', '一是', '二是', '三是', '四是', '五是',
          '主要原因', '揭示', '得益于', '协同', '有望', '拓展')


def flag_kind(section_key, claim):
    """被标句子 → 'exp' 实验清单 / 'fig' 图注描述 / 'infer' 归纳引申机理 / 'other'。规则判，不问模型。"""
    if section_key == 'exp':
        return 'exp'
    if _FIG_SENT.match(claim or ''):
        return 'fig'
    if any(w in (claim or '') for w in _INFER):
        return 'infer'
    return 'other'


def html_to_content(html):
    """summary.html → 跟 compose 产出同形的 markdown（审已经写好的精读用）。"""
    import html as _h
    body = re.search(r'<body>([\s\S]*)</body>', html)
    body = body.group(1) if body else html
    lines, n_img = [], 0
    for m in re.finditer(r'<(h1|h2|h3|p)[^>]*>([\s\S]*?)</\1>|<img\b[^>]*>', body):
        if not m.group(1):                       # 插进去的图按顺序还原成【图k】标记（插图就是按标记号插的）
            n_img += 1
            lines.append('【图%d】' % n_img)
            continue
        tag, inner = m.group(1), re.sub(r'<[^>]+>', '', m.group(2))
        inner = _h.unescape(inner).strip()
        if not inner:
            continue
        lines.append({'h1': '# ', 'h2': '## ', 'h3': '### ', 'p': ''}[tag] + inner)
    return '\n\n'.join(lines)


# ── 材料 ─────────────────────────────────────────────────────────────

def _material(key, md, si_md, outline, review, fig_map=None, units=None):
    if key == 'lead':
        return _sec.lead_material(md, outline)
    if key == 'exp':
        return _sec.exp_material(md, si_md, outline, review, units=units)
    if key.startswith('fig:'):
        i = int(key[4:])
        return _sec.fig_material(md, outline, (fig_map or {}).get(i, i))   # 标记号 → 图号
    if key == 'wrap':
        return _sec.wrap_material(md, outline)
    return (_ol.scan.clean_body(md or '') + '\n\n' + (si_md or ''))[:CAP_SOURCE]


def _captions(md, outline, cap=CAP_CAPTIONS):
    out, used = [], 0
    for f in outline.get('figures') or []:
        t = _ol.section_text(md, outline, f['id']).strip()
        if t:
            out.append(t)
            used += len(t)
            if used >= cap:
                break
    return '\n\n'.join(out)[:cap]


# ── 调模型 ───────────────────────────────────────────────────────────

def _ask(chat_json, sysp, user, local):
    if local:
        return chat_json(sysp, user, provider='ollama', temperature=0.0, num_ctx=NUM_CTX_LOCAL) or {}
    # 走路由（默认也是本机 Ollama，用户 2026-09-20 定）：窗口按本地档给，云端通道会忽略这个参数
    return chat_json(sysp, user, purpose=PURPOSE, temperature=0.1, num_ctx=NUM_CTX_LOCAL) or {}


_TOKEN = re.compile(r'\d+(?:\.\d+)?|[A-Za-z][A-Za-z0-9\-]{2,}')
_EMB_CACHE = {}        # 材料 hash → (段落列表, 向量列表)：同一栏的几批句子共用一次段落向量化
TOP_K = 3              # 每句取最像的几段


_EMB_OK: dict = {'v': None}


def _embed_ok():
    """向量服务在不在，每个进程只探一次（编程端 / 测试没有 Ollama：不能每段都去等 300 s 超时）。"""
    if _EMB_OK['v'] is None:
        try:
            from shared.adapters import embed as _e
            _EMB_OK['v'] = bool(_e.alive(timeout=3))
        except Exception:
            _EMB_OK['v'] = False
    return _EMB_OK['v']


def _para_vectors(material):
    from shared.adapters.embed import embed_batched
    h = hash(material)
    if h not in _EMB_CACHE:
        if len(_EMB_CACHE) > 8:
            _EMB_CACHE.clear()
        paras = [p for p in re.split(r'\n\s*\n', material) if p.strip()]
        _EMB_CACHE[h] = (paras, embed_batched(paras))
    return _EMB_CACHE[h]


def _cap_lexical(material, claims, cap):
    keys = {t.lower() for c in claims for t in _TOKEN.findall(c)}      # 数也在 keys 里，词面这条路本来就锚着数
    paras = [p for p in re.split(r'\n\s*\n', material) if p.strip()]
    scored = [(len(keys & {t.lower() for t in _TOKEN.findall(p)}), i) for i, p in enumerate(paras)]
    picked, used = set(), 0
    for hits, i in sorted(scored, key=lambda x: (-x[0], x[1])):
        if hits == 0 and used > cap // 2:
            break
        if used + len(paras[i]) > cap:
            continue
        picked.add(i)
        used += len(paras[i]) + 2
    return '\n\n'.join(paras[i][:6000] for i in sorted(picked))[:cap]


def _cap(material, claims, cap=CAP_LOCAL):
    """材料压到本地窗口装得下：装得下原样给；装不下**按句子挑段落**。

    2026-09-22 起用 bge-m3 语义检索（本地、跨语言）：每句取最像的 TOP_K 段，按相似度合并、按原文顺序拼到 cap。
    第一轮校准的误报大头就是「中文句子一个英文词都没有 → 词面重合挑不到段 → 判成编造」；语义检索没有这个问题。
    向量服务不在（编程端 / 测试）就退回词面重合那版。
    """
    if len(material) <= cap:
        return material
    if not _embed_ok():
        return _cap_lexical(material, claims, cap)
    try:
        from shared.adapters.embed import embed_batched, cosine
        paras, pv = _para_vectors(material)
        cv = embed_batched(list(claims))
        if not paras or not any(len(v) > 1 for v in pv) or not any(len(v) > 1 for v in cv):
            raise RuntimeError('no vectors')
    except Exception:
        return _cap_lexical(material, claims, cap)
    best = {}
    for c in cv:
        sims = sorted(((cosine(c, v), i) for i, v in enumerate(pv)), reverse=True)[:TOP_K]
        for s, i in sims:
            best[i] = max(best.get(i, 0.0), s)
    # 数字锚定（第五轮加过：待审句里的数所在的段必进窗口）已撤：实测净负（误报 12.0% → 13.7%），
    # 带数的段把语义相关段挤出去。数字改由 review() 里的脚本数字闸管（规划 §十四补、§十五）。
    picked, used = set(), 0
    for i, s in sorted(best.items(), key=lambda x: -x[1]):
        if i in picked or used + len(paras[i]) > cap:
            continue
        picked.add(i)
        used += len(paras[i]) + 2
    for i in range(len(paras)):                       # 还有余量就按顺序补没挑到的段（讨论段常紧挨着）
        if i in picked or used + len(paras[i]) > cap:
            continue
        picked.add(i)
        used += len(paras[i]) + 2
    return '\n\n'.join(paras[i][:6000] for i in sorted(picked))[:cap]


RETRY_BATCH = 3        # 漏判的句子补问时一批几句


def _judge(chat_json, claims, material, local, log, what, retry=True):
    """一批句子 + 材料 → [{'claim','v','why'}]。

    模型漏判的句子**缩小批量补问一次**（2026-09-22）：同一篇两次跑「判了几句」差很多（46 句里 33 到 46），
    分母在晃，误报率就一直在 12–14% 晃（规划 §十四补）。补问后还不答的才记 v='unjudged'。
    """
    out = _judge_once(chat_json, claims, material, local, log, what, BATCH_LOCAL if local else BATCH)
    if not retry:
        return out
    miss = [i for i, v in enumerate(out) if v['v'] == 'unjudged']
    if miss:
        again = _judge_once(chat_json, [out[i]['claim'] for i in miss], material, local, log,
                            what + '·补问', RETRY_BATCH)
        for i, v in zip(miss, again):
            if v['v'] != 'unjudged':
                v['retried'] = True
                out[i] = v
    return out


def _judge_once(chat_json, claims, material, local, log, what, size):
    out = []
    for start in range(0, len(claims), size):
        batch = claims[start:start + size]
        user = '【原文材料】\n%s\n\n【待审句子】\n%s' % (
            _cap(material, batch), '\n'.join('%d. %s' % (i + 1, c) for i, c in enumerate(batch)))
        try:
            d = _ask(chat_json, prompts.load('deepread', PROMPTS['claims']), user, local)
        except Exception as e:                 # 审稿失败不许拖垮精读：整批记 unjudged
            log('  审稿 %s 调用失败：%s' % (what, str(e)[:80]))
            d = {}
        got = {}
        for v in (d.get('verdicts') or []) if isinstance(d, dict) else []:
            try:
                i, verdict = int(v.get('i')), str(v.get('v') or '').strip().lower()
            except (TypeError, ValueError, AttributeError):
                continue
            if 1 <= i <= len(batch) and verdict in VERDICTS:
                got[i] = (verdict, str(v.get('why') or '')[:200])
        for i, c in enumerate(batch, 1):
            verdict, why = got.get(i, ('unjudged', ''))
            out.append({'claim': c, 'v': verdict, 'why': why})
    return out


def _recheck(chat_json, flagged, source, local, log):
    """被标的句子拿整篇原文再判一次。整篇里能找到依据的 → 切片漏了（slice_miss），不算编辑的错。"""
    if not flagged:
        return 0
    # 整篇原文原样交给 _judge，由 _cap 按句子挑段落。2026-09-23 前这里先截到前 CAP_SOURCE（6 万字）再挑 ——
    # 正文后半与 SI 根本进不了挑选范围，导读栏概括正文结果的句子复核也救不回来（第七轮逐条核对查出）
    verdicts = _judge(chat_json, [f['claim'] for f in flagged], source, local, log, '整篇复核')
    fixed = 0
    for f, v in zip(flagged, verdicts):
        if v['v'] in ('ok', 'skip'):
            f['v'], f['slice_miss'] = 'ok', True
            fixed += 1
    return fixed


def key_points(chat_json, md, outline, local=False, log=print):
    user = '【摘要】\n%s\n\n【结论】\n%s\n\n【全部图注】\n%s' % (
        _sec._by_kind(md, outline, (_ol.ABSTRACT,), 3000),
        _sec._by_kind(md, outline, (_ol.CONCLUSION,), _sec.CAP_CONCL),
        _captions(md, outline))
    try:
        d = _ask(chat_json, prompts.load('deepread', PROMPTS['keypoints']), user, local)
    except Exception as e:
        log('  要点清单调用失败：%s' % str(e)[:80])
        return []
    pts = []
    for p in (d.get('points') or []) if isinstance(d, dict) else []:
        if isinstance(p, dict) and str(p.get('text') or '').strip():
            pts.append({'k': str(p.get('k') or 'claim')[:10], 'text': str(p['text']).strip()[:300]})
    return pts[:15]


def coverage(chat_json, points, content, local=False, log=print):
    if not points:
        return []
    user = '【要点清单】\n%s\n\n【精读全文】\n%s' % (
        '\n'.join('%d. [%s] %s' % (i + 1, p['k'], p['text']) for i, p in enumerate(points)), content[:40000])
    try:
        d = _ask(chat_json, prompts.load('deepread', PROMPTS['cover']), user, local)
    except Exception as e:
        log('  覆盖判定调用失败：%s' % str(e)[:80])
        d = {}
    got = {}
    for c in (d.get('cover') or []) if isinstance(d, dict) else []:
        try:
            i, v = int(c.get('i')), str(c.get('v') or '').strip().lower()
        except (TypeError, ValueError, AttributeError):
            continue
        if 1 <= i <= len(points) and v in ('covered', 'partial', 'missed'):
            got[i] = (v, str(c.get('where') or '')[:40])
    return [dict(p, v=got.get(i, ('unjudged', ''))[0], where=got.get(i, ('', ''))[1])
            for i, p in enumerate(points, 1)]


def _judge_with_numbers(chat_json, claims, source, material, local, log, what):
    """数字闸（脚本）+ 模型。换什么模型都成立的那一半不交给模型。

    - 句中有原文（正文 + SI）里找不到的数（按完整数字、带单位的连单位比）→ 脚本直接判 unsupported，不问模型
    - 其余交给模型；模型判「原文没有」而句中 ≥2 个数在原文同一处凑齐 → 否决成 ok（`num_ok`）。
      「证据就在材料里、模型仍说原文没有」是第四、五轮查实的本地模型误报（规划 §十四补）
    """
    pre = {}
    for i, c in enumerate(claims):
        miss = _nums.ungrounded_numbers(c, source)       # 完整数字 + 连单位比（实测见 numcheck）
        if miss:
            pre[i] = {'claim': c, 'v': 'unsupported', 'by': 'script',
                      'why': '数字 %s 在原文（含 SI）里找不到（脚本核）' % '、'.join(miss[:3])}
    ask = [c for i, c in enumerate(claims) if i not in pre]
    judged = iter(_judge(chat_json, ask, material, local, log, what) if ask else [])
    out = []
    for i, c in enumerate(claims):
        v = pre.get(i) or next(judged)
        if v['v'] == 'unsupported' and v.get('by') != 'script' and _nums.grounded_together(c, source):
            v = dict(v, v='ok', num_ok=True)
        out.append(v)
    return out


# ── 主入口 ───────────────────────────────────────────────────────────

def review(content, md, si_md, chat_json, meta=None, log=print, local=False, points=None, with_cover=True, fig_map=None, units=None):
    """一篇精读 → 审稿报告。`points` 传上一轮抽好的要点清单就不再抽（回炉后复审省一次调用）。
    `fig_map` 是 {【图i】标记号: 图号}（compose 统计里的 numbered），不给就当两者相同。
    `units` 是这篇的单元库：实验栏的材料会附上制备步骤的原句（2026-09-22，见 sectioned.exp_material）。"""
    meta = meta or {}
    outline = _ol.build_outline(md, si_md=si_md or '')
    is_rev = _sec.is_review_doc(meta.get('title', ''), outline, meta.get('journal', ''), paper_type=meta.get('paper_type'))
    source = (md or '') + '\n' + (si_md or '')
    secs = {}
    all_flagged = []
    for key, name, text in sections_of(content):
        claims = split_claims(text)
        if not claims:
            continue
        verdicts = _judge_with_numbers(chat_json, claims, source,
                                       _material(key, md, si_md, outline, is_rev, fig_map, units), local, log, name)
        flagged = [v for v in verdicts if v['v'] in BAD]
        all_flagged += flagged
        secs[key] = {'name': name, 'n': len(claims), 'verdicts': verdicts,
                     'n_unjudged': sum(1 for v in verdicts if v['v'] == 'unjudged')}
    model_flagged = [f for f in all_flagged if f.get('by') != 'script']     # 脚本判的是确定的，不复核
    slice_miss = _recheck(chat_json, model_flagged, source, local, log) if model_flagged else 0
    for s in secs.values():
        s['flags'] = [v for v in s['verdicts'] if v['v'] in BAD]
    n_judged = sum(s['n'] - s['n_unjudged'] for s in secs.values())
    n_flag = sum(len(s['flags']) for s in secs.values())
    pts = points if points is not None else (key_points(chat_json, md, outline, local, log) if with_cover else [])
    cover = coverage(chat_json, pts, content, local, log) if (with_cover and pts) else []
    rep = {'version': VERSION, 'prompts': dict(PROMPTS), 'when': time.strftime('%Y-%m-%d %H:%M'),
           'n_claims': sum(s['n'] for s in secs.values()), 'n_judged': n_judged, 'n_flagged': n_flag,
           'flag_rate': round(n_flag / n_judged, 4) if n_judged else 0.0,
           'n_slice_miss': slice_miss,
           'n_script_flag': sum(1 for s in secs.values() for v in s['verdicts'] if v.get('by') == 'script' and v['v'] in BAD),
           'n_num_override': sum(1 for s in secs.values() for v in s['verdicts'] if v.get('num_ok')),
           'n_retried': sum(1 for s in secs.values() for v in s['verdicts'] if v.get('retried')),
           'sections': {k: {'name': s['name'], 'n': s['n'], 'n_unjudged': s['n_unjudged'], 'flags': s['flags'],
                            'slice_miss': [v['claim'][:80] for v in s['verdicts'] if v.get('slice_miss')][:10]}
                        for k, s in secs.items()},
           'points': pts, 'cover': cover,
           'n_missed': sum(1 for c in cover if c['v'] == 'missed'),
           'n_partial': sum(1 for c in cover if c['v'] == 'partial')}
    rep['passed'] = passed(rep)
    log('  审稿：%d 句判了 %d（补问救回 %d），标出 %d（%.1f%%，其中脚本核数 %d；数字否决误判 %d；切片漏判另 %d）；要点 %d 条漏 %d 半 %d → %s' % (
        rep['n_claims'], n_judged, rep['n_retried'], n_flag, rep['flag_rate'] * 100,
        rep['n_script_flag'], rep['n_num_override'], slice_miss,
        len(pts), rep['n_missed'], rep['n_partial'], '过' if rep['passed'] else '不过'))
    return rep


def passed(report):
    return report.get('flag_rate', 1.0) <= FLAG_TOL and report.get('n_missed', 99) <= MISS_TOL


def notes_for(report):
    """报告 → {栏 key: 回炉提示}。有被标句子的栏各一条；漏了要点的挂在收尾栏。"""
    notes = {}
    for k, s in (report.get('sections') or {}).items():
        if s.get('flags'):
            items = '；'.join('「%s…」（%s）' % (f['claim'][:40], f['why'] or ('原文没有' if f['v'] == 'unsupported' else '与原文不符'))
                              for f in s['flags'][:6])
            notes[k] = ('\n\n⚠ 审稿指出上一稿这些句子原文不支持：%s。删掉或改成原文的说法，'
                        '其余内容保持不变，按同样格式重写。' % items)
    missed = [c for c in report.get('cover') or [] if c['v'] == 'missed']
    if missed and len(missed) > MISS_TOL:
        notes['wrap'] = notes.get('wrap', '') + ('\n\n⚠ 审稿指出精读漏了这些要点，在 Q2 或总之里补上（照原文的数值与说法）：%s'
                                                % '；'.join(c['text'][:120] for c in missed[:5]))
    return notes


def to_markdown(report, key=''):
    """给人看的一页（进「待人看」清单时附上）。"""
    L = ['# 审稿报告 %s' % key, '', '%s · %d 句判 %d · 标出 %d（%.1f%%）· 要点 %d 漏 %d 半 %d · **%s**' % (
        report.get('when', ''), report.get('n_claims', 0), report.get('n_judged', 0), report.get('n_flagged', 0),
        report.get('flag_rate', 0) * 100, len(report.get('points') or []), report.get('n_missed', 0),
        report.get('n_partial', 0), '过' if report.get('passed') else '不过'), '']
    for k, s in (report.get('sections') or {}).items():
        for f in s.get('flags') or []:
            L.append('- [%s] %s：%s —— %s' % (s['name'], f['v'], f['claim'], f['why']))
    for c in report.get('cover') or []:
        if c['v'] in ('missed', 'partial'):
            L.append('- [要点 %s] %s：%s' % (c['v'], c['k'], c['text']))
    return '\n'.join(L) + '\n'
