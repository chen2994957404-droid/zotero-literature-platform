# -*- coding: utf-8 -*-
"""单元拆解研究（2026-09-20）：把人写的范文拆成七类最小信息单元，量「基本单元长什么样」。

**为什么先做这个**：本地化拆解的正确顺序是先搞清最小的、互不依赖的单元和它们之间的联系，再定每步用什么模型
（用户 2026-09-20 定；方法依据见 docs/reference/本地化拆解_方法调研.md：FActScore 的原子事实、
Pyramid 的内容单元、Kononova/ULSA 的合成动作、ChemDataExtractor 的性质元组）。

做法：范文按段切 → 每段让本地模型拆成 entity / fact / action / panel / claim / role / cause 七类单元（JSON）
→ 脚本给每条单元定位：它属于范文的哪一栏、它的数值/名字落在原文的哪个位置（骨架的哪类节、全文的几分之几处）
→ 汇总成 报告：每篇每类多少条、平均多长、栏 × 类矩阵、每类单元在原文的位置分布。

产物：data/state/unit_study/<tag>/<pid>.json（逐条单元）+ summary.json + report.md。**只读范文与原文，不写别处。**

用法：python -m tools.deepread --单元拆解 --篇数 20 --本地 --tag u1
"""
import io
import json
import os
import re
import time

from shared.kernel import paths, prompts
from shared.domain.schema import outline as _ol

PROMPT = 'units@v1'
TYPES = ('entity', 'fact', 'action', 'panel', 'claim', 'role', 'cause')
PARA_TARGET = 900        # 相邻短段攒到这么多字再送一次（一次别太长，本地模型漏条）
NUM_CTX = 8192

_NUM = re.compile(r'\d+(?:\.\d+)?')
_LATIN = re.compile(r'[A-Za-z][A-Za-z0-9\-]{2,}')


# ── 范文分栏（人写的，靠标记词）─────────────────────────────────────

def column_of(para, prev):
    """范文段落 → 栏名。靠范式里的固定起笔：近期(导读) / (1)主要实验药品(实验) / Question(Q1/Q2) / 图N(图) / 总之 / 通俗理解。"""
    p = para.strip()
    if p.startswith('近期') or '报道了' in p[:60] or '系统总结了' in p[:60]:
        return '导读'
    if re.match(r'^[（(]?1[）)]?\s*主要实验药品|^[（(]1[）)]', p) or p.startswith('主要实验药品'):
        return '实验'
    if p.startswith('Question') or p.startswith('问题'):
        return 'Q2' if '性能' in p[:40] and '优异' in p[:60] else 'Q1'
    if re.match(r'^[▲▼]?\s*图\s*\d', p) or re.match(r'^\[?Fig', p, re.I):
        return '图'
    if p.startswith('总之'):
        return '总之'
    if p.startswith('通俗理解'):
        return '通俗理解'
    if p.startswith('文献信息') or p.startswith('DOI') or p.startswith('原文链接'):
        return '文献信息'
    if prev in ('导读',) and len(p) > 60:
        return '引言'
    return prev or '引言'


def paragraphs(ref_text):
    """范文 → [(栏, 段)]。图链接行、空行丢掉；短段攒到 PARA_TARGET。"""
    out, cur, buf, used = [], '', [], 0
    for raw in ref_text.split('\n'):
        p = raw.strip()
        if not p or p.startswith('![') or p.startswith('#') or p.startswith('来源:') or p.startswith('---'):
            continue
        col = column_of(p, cur)
        if buf and (col != cur or used + len(p) > PARA_TARGET):
            out.append((cur, '\n'.join(buf)))
            buf, used = [], 0
        cur = col
        buf.append(p)
        used += len(p)
    if buf:
        out.append((cur, '\n'.join(buf)))
    return [(c, t) for c, t in out if c != '文献信息']


# ── 调模型 ───────────────────────────────────────────────────────────

def split_units(chat_json, col, text, local=True, log=print):
    sysp = prompts.load('deepread', PROMPT)
    user = '这一段属于精读的「%s」栏。\n\n%s' % (col, text)
    try:
        if local:
            d = chat_json(sysp, user, provider='ollama', temperature=0.0, num_ctx=NUM_CTX) or {}
        else:
            d = chat_json(sysp, user, purpose='REVIEW', temperature=0.1) or {}
    except Exception as e:
        log('  拆解调用失败：%s' % str(e)[:80])
        return [], True
    units = []
    for u in (d.get('units') or []) if isinstance(d, dict) else []:
        if isinstance(u, dict) and str(u.get('type') or '').strip().lower() in TYPES:
            u = {k: (str(v) if not isinstance(v, (list, dict)) else v) for k, v in u.items()}
            u['type'] = u['type'].strip().lower()
            u['col'] = col
            units.append(u)
    return units, False


# ── 定位：这条单元的数值 / 名字落在原文哪里 ──────────────────────────

def _probe_tokens(u):
    """从单元里挑能在英文原文里找到的东西：数值优先，其次样品编号 / 缩写这类拉丁串。"""
    vals = []
    for k in ('value', 'amounts', 'conditions', 'key_value'):
        v = u.get(k)
        if isinstance(v, list):
            v = ' '.join(str(x) for x in v)
        if v:
            vals += _NUM.findall(str(v))
    names = []
    for k in ('sample', 'name', 'abbr', 'materials', 'component', 'product', 'design'):
        v = u.get(k)
        if isinstance(v, list):
            v = ' '.join(str(x) for x in v)
        if v:
            names += [t for t in _LATIN.findall(str(v)) if len(t) >= 3]
    return [x for x in vals if len(x) >= 2 and x not in ('10', '20', '100')], names[:4]


def locate(u, md, outline, si_md=''):
    """→ {'where': 'main'|'si'|'none', 'kind': 骨架节类, 'pos': 全文位置 0–1}。找不到就 none。"""
    nums, names = _probe_tokens(u)
    for where, text in (('main', md), ('si', si_md)):
        if not text:
            continue
        hit = -1
        for n in nums:
            m = re.search(r'(?<![\d.])' + re.escape(n) + r'(?![\d])', text)
            if m:
                hit = m.start()
                break
        if hit < 0 and nums == [] and names:
            for nm in names:
                m = re.search(r'\b' + re.escape(nm) + r'\b', text)
                if m:
                    hit = m.start()
                    break
        if hit >= 0:
            kind = ''
            if where == 'main':
                for s in outline.get('sections') or []:
                    if s['start'] <= hit < s['end']:
                        kind = s['kind']
                        break
            return {'where': where, 'kind': kind, 'pos': round(hit / max(1, len(text)), 3)}
    return {'where': 'none', 'kind': '', 'pos': None}


# ── 跑与汇总 ─────────────────────────────────────────────────────────

def run_one(pid, chat_json, local=True, log=print):
    ref = io.open(paths.reference(pid), encoding='utf-8').read()
    md = io.open(paths.fulltext(pid), encoding='utf-8').read()
    sp = paths.si_fulltext(pid)
    si = io.open(sp, encoding='utf-8').read() if os.path.exists(sp) else ''
    outline = _ol.build_outline(md)
    paras = paragraphs(ref)
    units, failed = [], 0
    for i, (col, text) in enumerate(paras):
        us, bad = split_units(chat_json, col, text, local, log)
        failed += bad
        for u in us:
            u['para'] = i
            u['len'] = len(json.dumps({k: v for k, v in u.items() if k not in ('col', 'para', 'src')}, ensure_ascii=False))
            u['loc'] = locate(u, md, outline, si)
        units += us
        log('  [%d/%d] %s 段 %d 字 → %d 条' % (i + 1, len(paras), col, len(text), len(us)))
    return {'pid': pid, 'n_paras': len(paras), 'ref_chars': len(ref), 'failed_paras': failed,
            'has_si': bool(si), 'units': units}


def summarize(results):
    by_type = {t: {'n': 0, 'len': 0, 'located_main': 0, 'located_si': 0, 'none': 0, 'kinds': {}, 'pos': []} for t in TYPES}
    col_type = {}
    per_paper = []
    for r in results:
        cnt = {t: 0 for t in TYPES}
        for u in r['units']:
            t = u['type']
            cnt[t] += 1
            b = by_type[t]
            b['n'] += 1
            b['len'] += u.get('len', 0)
            loc = u.get('loc') or {}
            if loc.get('where') == 'main':
                b['located_main'] += 1
                b['kinds'][loc.get('kind') or '?'] = b['kinds'].get(loc.get('kind') or '?', 0) + 1
                b['pos'].append(loc.get('pos'))
            elif loc.get('where') == 'si':
                b['located_si'] += 1
            else:
                b['none'] += 1
            col_type.setdefault(u.get('col', '?'), {t2: 0 for t2 in TYPES})[t] += 1
        per_paper.append({'pid': r['pid'], 'ref_chars': r['ref_chars'], 'n_paras': r['n_paras'],
                          'failed_paras': r['failed_paras'], 'has_si': r['has_si'], **cnt,
                          'total': sum(cnt.values())})
    for t, b in by_type.items():
        b['avg_len'] = round(b['len'] / b['n'], 1) if b['n'] else 0
        ps = sorted(p for p in b['pos'] if p is not None)
        b['pos_quartiles'] = [ps[len(ps) * q // 4] for q in (1, 2, 3)] if len(ps) >= 4 else ps
        del b['pos'], b['len']
    return {'per_paper': per_paper, 'by_type': by_type, 'col_type': col_type}


def write_report(out_dir, tag, summary, when):
    L = ['# 单元拆解 %s（%s）' % (tag, when), '',
         '%d 篇范文。每篇每类单元数：' % len(summary['per_paper']), '',
         '| 篇 | 范文字数 | 段 | ' + ' | '.join(TYPES) + ' | 合计 |', '|---|---|---|' + '---|' * (len(TYPES) + 1)]
    for r in summary['per_paper']:
        L.append('| %s | %d | %d | %s | %d |' % (r['pid'], r['ref_chars'], r['n_paras'],
                                                ' | '.join(str(r[t]) for t in TYPES), r['total']))
    L += ['', '## 每类单元：多少条、多长、在原文哪里（定位靠数值 / 样品名 / 缩写，找不到记 none）', '',
          '| 类 | 条数 | 平均长度(字符) | 定位到正文 | 定位到 SI | 没定位到 | 正文里落在哪类节 | 正文位置四分位 |',
          '|---|---|---|---|---|---|---|---|']
    for t in TYPES:
        b = summary['by_type'][t]
        kinds = '、'.join('%s %d' % kv for kv in sorted(b['kinds'].items(), key=lambda x: -x[1])[:4])
        L.append('| %s | %d | %s | %d | %d | %d | %s | %s |' % (
            t, b['n'], b['avg_len'], b['located_main'], b['located_si'], b['none'], kinds or '—',
            ' / '.join(str(p) for p in b['pos_quartiles']) or '—'))
    L += ['', '## 栏 × 类（范文的每一栏由哪些单元组成）', '',
          '| 栏 | ' + ' | '.join(TYPES) + ' |', '|---|' + '---|' * len(TYPES)]
    for col, row in summary['col_type'].items():
        L.append('| %s | %s |' % (col, ' | '.join(str(row[t]) for t in TYPES)))
    io.open(os.path.join(out_dir, 'report.md'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')


def run(keys, chat_json, tag='u1', local=True, log=print):
    out_dir = paths.unit_study_dir(tag)
    os.makedirs(out_dir, exist_ok=True)
    results = []
    for i, pid in enumerate(keys, 1):
        f = os.path.join(out_dir, pid + '.json')
        if os.path.exists(f):
            results.append(json.load(io.open(f, encoding='utf-8')))
            log('[%d/%d] %s 已有，跳过' % (i, len(keys), pid))
            continue
        if not (os.path.exists(paths.reference(pid)) and os.path.exists(paths.fulltext(pid))):
            log('[%d/%d] %s 缺范文或全文，跳过' % (i, len(keys), pid))
            continue
        log('[%d/%d] %s' % (i, len(keys), pid))
        r = run_one(pid, chat_json, local, log)
        json.dump(r, io.open(f, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        results.append(r)
    when = time.strftime('%Y-%m-%d %H:%M')
    summary = summarize(results)
    json.dump({'tag': tag, 'when': when, **summary}, io.open(os.path.join(out_dir, 'summary.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    write_report(out_dir, tag, summary, when)
    return summary, os.path.join(out_dir, 'report.md')
