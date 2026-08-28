# -*- coding: utf-8 -*-
"""比一比两个模型：同一篇文献、同样的料、同一套提示词，**只看不写**。

用法:
  python 试一试本地模型.py                    # 自动挑 3 篇，本地 vs 云端
  python 试一试本地模型.py --n 5              # 挑 5 篇
  python 试一试本地模型.py <KEY> <KEY> …      # 指定篇目
  python 试一试本地模型.py <KEY> --only-local # 只跑本地（不花钱）

为什么要有这个（2026-08-28）：「本地 qwen 够不够用」这种问题，
**光靠印象回答是不可信的**（宪法零号判据）。跑几篇、把两边的字段并排摆出来，
再自动算三个指标，哪一边虚、哪一边编，一眼看得见。

三个指标（都不需要人工标注，跑完就有）：
  有值字段   填出了多少个字段（空/N/A 不算）—— 衡量「敢不敢答」
  数值条数   key_properties 里能解析成数的有几条 —— 衡量「答得有多具体」
  数字可追溯 抽出来的数字有多少能在原文里逐字找到 —— **衡量有没有编**

第三个是关键。但它是粗判据：单位换算、0.9 vs 90% 都会算成「没找到」，
所以下面会把没找到的那些**具体列出来**，一眼就能分清是换算还是瞎编。

**绝不写盘**：结果只打印，不覆盖 `structured/<key>.json`（踩坑 #16）。
"""
import io
import json
import os
import sys
import time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from core import paths
from core.cli import flag, opt, positionals
from core.config import get_key
from domain import schema
from pipelines import extract

SHOW = ['material_system', 'dynamic_bond_type', 'precursors', 'synthesis_conditions',
        'characterization', 'key_properties', 'self_healing', 'key_finding']


def _one(provider, title, body, si):
    """跑一次抽取（不带自检重抽循环 —— A/B 要比的是模型本身）。返回 (data, 秒)。"""
    old = os.environ.get('EXTRACT_PROVIDER')
    os.environ['EXTRACT_PROVIDER'] = provider
    t = time.time()
    try:
        data = extract.llm_json(schema.SYS, schema.build_user_prompt(title, body, si))
    finally:
        if old is None:
            os.environ.pop('EXTRACT_PROVIDER', None)
        else:
            os.environ['EXTRACT_PROVIDER'] = old
    return data, round(time.time() - t, 1)


def _fmt(v, width=260):
    if isinstance(v, (list, tuple)):
        v = '; '.join(str(x) for x in v)
    return str(v).replace('\n', ' ')[:width]


def _metrics(data, source):
    """三个指标：有值字段 / 数值条数 / 数字可追溯。"""
    filled = sum(1 for f in schema.SCHEMA if schema.has_value((data or {}).get(f)))
    nums = sum(1 for p in schema.parse_properties(data or {}) if p['value'] is not None)
    hit, total, miss = schema.number_grounding(data, source)
    return {'filled': filled, 'nums': nums, 'hit': hit, 'total': total, 'miss': miss}


def _load(key):
    """一篇的标题 / 正文 / SI / 已有记录；缺 full.md 返回 None。"""
    md = paths.fulltext(key)
    if not os.path.exists(md):
        return None
    meta = {}
    if os.path.exists(paths.meta(key)):
        try:
            meta = json.load(io.open(paths.meta(key), encoding='utf-8'))
        except Exception:
            pass
    raw = io.open(md, encoding='utf-8').read()
    old = None
    if os.path.exists(paths.structured(key)):
        try:
            old = json.load(io.open(paths.structured(key), encoding='utf-8'))
        except Exception:
            pass
    return {'title': meta.get('title') or key,
            'body': schema.hierarchical_body(raw),
            'si': extract.si_text(key), 'raw': raw, 'old': old}


def compare_one(key, only_local=False):
    """跑一篇的对比，打印细节，返回两边的指标。"""
    d = _load(key)
    if not d:
        print(f'[跳过] {key} 没有 parsed/full.md')
        return None
    source = d['raw'] + '\n' + d['si']        # 数字回原文核对时，正文和 SI 都算
    print(f'\n{"=" * 76}\n{key}  {d["title"][:60]}')
    print(f'正文 {len(d["body"])} 字符，SI {len(d["si"])} 字符')

    local, t_local = _one('ollama', d['title'], d['body'], d['si'])
    print(f'  本地 {get_key("OLLAMA_MODEL", default="ollama")}：{t_local}s')
    cloud, t_cloud = (None, 0)
    if not only_local:
        cloud, t_cloud = _one('deepseek', d['title'], d['body'], d['si'])
        print(f'  云端 DeepSeek：{t_cloud}s')

    for f in SHOW:
        print(f'\n■ {f}')
        print(f'  本地: {_fmt(local.get(f))}')
        if cloud is not None:
            print(f'  云端: {_fmt(cloud.get(f))}')
    m_local = _metrics(local, source)
    m_cloud = _metrics(cloud, source) if cloud is not None else None
    print(f'\n  本地: 有值 {m_local["filled"]}/{len(schema.SCHEMA)}，'
          f'数值 {m_local["nums"]} 条，数字可追溯 {m_local["hit"]}/{m_local["total"]}')
    if m_local['miss']:
        print(f'    原文里找不到的数字：{"; ".join(m_local["miss"][:6])}')
    if m_cloud:
        print(f'  云端: 有值 {m_cloud["filled"]}/{len(schema.SCHEMA)}，'
              f'数值 {m_cloud["nums"]} 条，数字可追溯 {m_cloud["hit"]}/{m_cloud["total"]}')
        if m_cloud['miss']:
            print(f'    原文里找不到的数字：{"; ".join(m_cloud["miss"][:6])}')
    return {'key': key, 'local': m_local, 'cloud': m_cloud,
            't_local': t_local, 't_cloud': t_cloud}


def main():
    only_local = flag('--only-local')
    keys = [paths.check_key(k) for k in positionals()]
    if not keys:
        n = int(opt('--n', 3))
        pool = [k for k in paths.all_keys() if os.path.exists(paths.si_fulltext(k))
                and os.path.exists(paths.fulltext(k))]
        keys = pool[:n]
    print(f'比 {len(keys)} 篇：{"只跑本地" if only_local else "本地 vs 云端"}'
          f'（只打印，不写盘）')

    rows = [r for r in (compare_one(k, only_local) for k in keys) if r]
    if not rows:
        return
    print(f'\n{"=" * 76}\n汇总（{len(rows)} 篇）\n')
    print(f'{"":6s}{"有值字段":>10s}{"数值条数":>10s}{"数字可追溯":>12s}{"每篇秒数":>10s}')
    for side in ('local', 'cloud'):
        vals = [r[side] for r in rows if r.get(side)]
        if not vals:
            continue
        hit = sum(v['hit'] for v in vals)
        tot = sum(v['total'] for v in vals)
        secs = sum(r['t_local' if side == 'local' else 't_cloud'] for r in rows) / len(rows)
        print(f'{"本地" if side == "local" else "云端":6s}'
              f'{sum(v["filled"] for v in vals) / len(vals):10.1f}'
              f'{sum(v["nums"] for v in vals) / len(vals):10.1f}'
              f'{(hit / tot * 100 if tot else 0):11.0f}%'
              f'{secs:10.0f}')
    print('\n「数字可追溯」低不一定是编的 —— 单位换算、90% 写成 0.9 都会算没找到。'
          '\n上面每篇都列出了找不到的具体数字，扫一眼就知道是哪种。')


if __name__ == '__main__':
    main()
