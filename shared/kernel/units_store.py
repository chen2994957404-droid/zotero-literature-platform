# -*- coding: utf-8 -*-
"""units_store · 单元库：契约 + 读写（2026-09-22 立）。`curated/<id>/units.json`。

**为什么**：单元研究（docs/explain/本地化拆解规划.md 第七、八节）证明精读、抽取、审稿、问答要的是同一批东西：
实体 / 数值事实 / 定性性质 / 合成动作 / 表征手段 / 图面板 / 主张 / 角色 / 因果。一篇文献只拆一次，落成单元库，
后面所有工具读它 —— 模型从「每个工具各读一遍全文」变成「拆一次，各处复用」。

**为什么住 kernel**：形状与落盘住一起是 `catalog.py`（meta.json）的先例；kernel 不许 import domain，
而落盘要 paths，所以契约跟着存取走，不拆两处。

一条单元长这样：
    {'id': 'fact:3f2a…',                 # type + 关键字段的哈希：同一件事再抽一次得到同一个 id
     'type': 'fact',
     'fields': {'sample': 'FC-EtFe', 'property': 'tensile strength', 'value': '7.11 MPa', 'unit': 'MPa', 'condition': ''},
     'src': {'where': 'main', 'quote': '…a greatly enhanced strength of 7.11 MPa…', 'pos': 0.31, 'location': 'Fig. 2'},
     'by': {'producer': 'fine_fact', 'model': 'qwen3.5:4b', 'ver': 1, 'when': '2026-09-22'},
     'checks': {'dimension_ok': True, 'sample_in_window': True}}

对外接口：
    TYPES / FIELDS / KEY_FIELDS         九类与各自的字段（必填 True）、进 id 的关键字段
    make_unit(type, fields, src, by, checks) → dict（算好 id，缺必填字段抛 ValueError）
    unit_id / validate / dedupe / to_json   纯逻辑
    load(key) / save(key, units) / merge(key, new_units, producer=None) / stats(units)   读写
"""
import hashlib
import io
import json
import os
import re

from shared.kernel import paths

TYPES = ('entity', 'fact', 'attribute', 'action', 'method', 'panel', 'claim', 'role', 'cause')

# 字段名 → 是否必填；关键字段（进 id 的）打 * 标在 KEY_FIELDS 里
FIELDS = {
    'entity':    {'name': True, 'abbr': False, 'kind': False},
    'fact':      {'sample': False, 'property': True, 'value': True, 'unit': False, 'condition': False},
    'attribute': {'sample': False, 'property': True, 'description': True},
    'action':    {'action': True, 'materials': False, 'amounts': False, 'conditions': False, 'product': False, 'order': False},
    'method':    {'technique': True, 'measures': False, 'instrument': False},
    'panel':     {'figure': True, 'subpanel': False, 'shows': True, 'key_value': False},
    'claim':     {'text': True},
    'role':      {'component': True, 'function': True},
    'cause':     {'design': True, 'effect': True},
}
KEY_FIELDS = {
    'entity': ('name',), 'fact': ('sample', 'property', 'value'), 'attribute': ('sample', 'property'),
    'action': ('action', 'materials', 'product'), 'method': ('technique',), 'panel': ('figure', 'subpanel'),
    'claim': ('text',), 'role': ('component', 'function'), 'cause': ('design', 'effect'),
}
SCHEMA_VER = 1


def _norm(v):
    if isinstance(v, (list, tuple)):
        return '|'.join(_norm(x) for x in v)
    return re.sub(r'\s+', ' ', str(v or '')).strip().lower()


def unit_id(type_, fields):
    """type + 关键字段（归一后）的短哈希。同一件事再抽一次 id 不变 —— 去重、增量更新都靠它。"""
    key = '\x1f'.join(_norm(fields.get(k)) for k in KEY_FIELDS[type_])
    return '%s:%s' % (type_, hashlib.sha1((type_ + '\x1f' + key).encode('utf-8')).hexdigest()[:12])


def validate(unit):
    """→ 问题列表；空 = 合格。只查形状，不查内容对不对（那是审稿的事）。"""
    bad = []
    t = unit.get('type')
    if t not in TYPES:
        bad.append('type 不在九类里：%r' % (t,))
        return bad
    f = unit.get('fields') or {}
    for name, required in FIELDS[t].items():
        if required and not _norm(f.get(name)):
            bad.append('%s 缺必填字段 %s' % (t, name))
    for name in f:
        if name not in FIELDS[t]:
            bad.append('%s 有未知字段 %s' % (t, name))
    if not (unit.get('src') or {}).get('quote'):
        bad.append('没有原文引用（src.quote）—— 单元必须能回到原文')
    if unit.get('id') != unit_id(t, f):
        bad.append('id 与字段不符')
    return bad


def make_unit(type_, fields, src, by, checks=None):
    """造一条合格的单元；缺必填字段抛 ValueError。"""
    if type_ not in TYPES:
        raise ValueError('type 不在九类里：%r' % (type_,))
    fields = {k: (v if isinstance(v, list) else str(v or '').strip()) for k, v in fields.items() if k in FIELDS[type_]}
    u = {'id': unit_id(type_, fields), 'type': type_, 'fields': fields,
         'src': {'where': src.get('where', 'main'), 'quote': str(src.get('quote', ''))[:300],
                 'pos': src.get('pos'), 'location': src.get('location', '')},
         'by': dict(by), 'checks': dict(checks or {})}
    problems = validate(u)
    if problems:
        raise ValueError('; '.join(problems))
    return u


def _strength(u):
    c = u.get('checks') or {}
    return (sum(1 for v in c.values() if v is True), bool((u.get('fields') or {}).get('sample')))


def dedupe(units):
    """同 id 只留一条：checks 通过得多的、带样品的优先；都一样留先来的。"""
    best = {}
    order = []
    for u in units:
        i = u['id']
        if i not in best:
            best[i] = u
            order.append(i)
        elif _strength(u) > _strength(best[i]):
            best[i] = u
    return [best[i] for i in order]


def to_json(paper_id, units):
    return json.dumps({'paper': paper_id, 'schema_ver': SCHEMA_VER, 'units': units}, ensure_ascii=False, indent=1)


# ── 读写 ──────────────────────────────────────────────────────────────

def load(key):
    p = paths.units(key)
    if not os.path.exists(p):
        return []
    try:
        d = json.load(io.open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return d.get('units') or []


def save(key, units):
    p = paths.units(key)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    io.open(tmp, 'w', encoding='utf-8').write(to_json(key, dedupe(units)))
    os.replace(tmp, p)
    return p


def merge(key, new_units, producer=None):
    old = load(key)
    if producer:
        old = [u for u in old if (u.get('by') or {}).get('producer') != producer]
    ids = {u['id'] for u in new_units}
    kept = [u for u in old if u['id'] not in ids]
    merged = kept + list(new_units)
    save(key, merged)
    return merged


def stats(units):
    d = {}
    for u in units:
        d[u.get('type', '?')] = d.get(u.get('type', '?'), 0) + 1
    return d
