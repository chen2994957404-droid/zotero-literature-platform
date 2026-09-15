# -*- coding: utf-8 -*-
"""对着人写的范文打分（纯函数，不碰文件系统）。2026-09-15。

**标尺**：`data/curated/<id>/reference.md` —— 高分子学人的真实推送（774 对，
`docs/reference/精读范式_实测.md` 里的范式就是从它们量出来的）。
以前精读好不好只能模型之间互比；现在每一篇都有一个「人写的答案」可对。

量的都是**脚本能算的**（改模板、换模型跑一遍就有分，不用人打分）：

    骨架        范式的 10 项栏目我们有几项
    图两段      有图注的图里，索引段 + ▲深解段都齐的占几成
    篇幅比      我们的字数 / 范文字数（目标 0.8–1.5，写不满不许编，写太长是啰嗦）
    数字覆盖    范文里带单位的数，我们写出来了几成（漏数 = 漏了范文认为重要的事实）
    术语覆盖    范文里的英文缩写 / 样品编号，我们用了几成（叫错名 = 读者对不上原文）
    Question    两问各几条（范文中位 7 / 6）
    通俗理解    有没有

`score()` 返回各项 + 一个 0–100 的综合分；综合分只用来排序和看趋势，
**单项才是能指导改什么的**。指标口径变了就把 `GOLDEN_VER` +1，旧分不再可比。
"""
import html as _html
import re

GOLDEN_VER = 1

SKELETON = ('## 导读', '## 引言', '（1）', '（2）', '（3）', 'Question：各', '## 讨论',
            'Question：本论文', '总之，', '## 文献信息')
_NUM_UNIT = re.compile(r'(\d+(?:\.\d+)?)\s*(?:wt%|vol%|mol%|%|℃|°C|kPa|MPa|GPa|Pa·s|Pa|nm|μm|um|mm|cm|'
                       r'kJ|J|mol|Hz|kHz|min|h|s⁻¹|s|g/mol|kDa|Da|mg|g|mL|L|V|mA|W|K|°)(?![A-Za-z])')
_ABBR = re.compile(r'\b[A-Z][A-Z0-9]{1,}(?:-[A-Za-z0-9]+)*\b')
_CJK = re.compile(r'[一-鿿]')


def text_of_html(html):
    """精读 HTML → 纯文本（段落之间保留换行；图片、样式剔掉）。"""
    body = re.sub(r'<img[^>]*>', '', html or '')
    body = re.sub(r'<style[\s\S]*?</style>|<script[\s\S]*?</script>', '', body)
    body = re.sub(r'<h1[^>]*>', '\n# ', body)
    body = re.sub(r'<h2[^>]*>', '\n## ', body)
    body = re.sub(r'</(?:p|h1|h2|h3|div)>', '\n', body)
    body = re.sub(r'<[^>]+>', '', body)
    body = _html.unescape(body)
    return re.sub(r'\n{2,}', '\n', body).strip()


def text_of_reference(md):
    """reference.md → 正文（去掉头部四行与图片链接）。"""
    lines = (md or '').split('\n')
    if '---' in lines:
        lines = lines[lines.index('---') + 1:]
    return '\n'.join(l for l in lines if l.strip() and not l.startswith('![')).strip()


def _numbers(text):
    return {m.group(1).rstrip('0').rstrip('.') if '.' in m.group(1) else m.group(1)
            for m in _NUM_UNIT.finditer(text or '')}


def _terms(text):
    out = set()
    for m in _ABBR.finditer(text or ''):
        t = m.group(0)
        if len(t) >= 3 and not t.isdigit() and t not in ('DOI', 'PDF', 'SI', 'HTML', 'THE', 'AND', 'FOR'):
            out.add(t)
    return out


def _cjk_len(text):
    return len(_CJK.findall(text or ''))


def score(ours_text, ref_text):
    """我们的精读（纯文本）vs 范文（纯文本）→ dict。两个都是 `text_of_*` 出来的。"""
    o, r = ours_text or '', ref_text or ''
    d = {'ver': GOLDEN_VER}
    d['skeleton'] = sum(1 for k in SKELETON if k in o)
    d['skeleton_max'] = len(SKELETON)
    idx = len(re.findall(r'(?m)^图\d+，', o))
    deep = len(re.findall(r'(?m)^▲图\d+', o))
    d['figs_idx'], d['figs_deep'] = idx, deep
    d['fig_two_para'] = round(min(idx, deep) / max(idx, deep), 2) if max(idx, deep) else 0.0
    d['chars'], d['ref_chars'] = _cjk_len(o), _cjk_len(r)
    d['length_ratio'] = round(d['chars'] / d['ref_chars'], 2) if d['ref_chars'] else 0.0
    rn, on = _numbers(r), _numbers(o)
    d['ref_numbers'] = len(rn)
    d['number_coverage'] = round(len(rn & on) / len(rn), 2) if rn else 1.0
    d['numbers_missed'] = sorted(rn - on)[:15]
    rt, ot = _terms(r), _terms(o)
    d['ref_terms'] = len(rt)
    d['term_coverage'] = round(len(rt & ot) / len(rt), 2) if rt else 1.0
    d['terms_missed'] = sorted(rt - ot)[:15]
    d['q1_items'] = o.count('🍁')
    d['q2_items'] = o.count('☘')
    d['ref_q1_items'], d['ref_q2_items'] = r.count('🍁'), r.count('☘')
    d['has_plain'] = '通俗理解' in o
    d['ref_has_plain'] = '通俗理解' in r
    d['composite'] = composite(d)
    return d


def composite(d):
    """0–100 的综合分。权重是判断，不是测出来的 —— 只用来排序和看趋势。

    骨架 25 · 图两段 15 · 篇幅 15（0.8–1.5 满分，越远越扣）· 数字覆盖 25 · 术语覆盖 10 · 两问 + 通俗 10
    """
    s = 25 * d['skeleton'] / d['skeleton_max']
    s += 15 * d['fig_two_para']
    lr = d['length_ratio']
    s += 15 * (1.0 if 0.8 <= lr <= 1.5 else max(0.0, 1 - abs(lr - (0.8 if lr < 0.8 else 1.5)) / 1.0))
    s += 25 * d['number_coverage']
    s += 10 * d['term_coverage']
    q = (min(d['q1_items'], 5) / 5 + min(d['q2_items'], 5) / 5) / 2
    s += 7 * q + (3 if d['has_plain'] else 0)
    return round(s, 1)


def aggregate(rows):
    """一批 score() → 各项中位数 + 综合分中位数（给报告用）。"""
    if not rows:
        return {}
    def med(k):
        xs = sorted(r[k] for r in rows if isinstance(r.get(k), (int, float)))
        return xs[len(xs) // 2] if xs else None
    keys = ('composite', 'skeleton', 'fig_two_para', 'length_ratio', 'number_coverage',
            'term_coverage', 'q1_items', 'q2_items', 'chars', 'ref_chars')
    out = {k: med(k) for k in keys}
    out['n'] = len(rows)
    out['plain_rate'] = round(sum(1 for r in rows if r['has_plain']) / len(rows), 2)
    return out
