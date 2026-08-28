# -*- coding: utf-8 -*-
"""本地模型能不能干这活？—— 拿同一篇文献做 A/B，**只看不写**。

用法:
  python 试一试本地模型.py <KEY>              # 本地模型抽一遍，和已有的云端结果并排比
  python 试一试本地模型.py <KEY> --both       # 云端也重跑一遍（花钱，默认不跑）

为什么要有这个（2026-08-28）：「本地 qwen 够不够用」这种问题，
**光靠印象回答是不可信的**（宪法零号判据）。跑一篇、把两边的字段并排摆出来，
哪一栏空、哪一栏编了，一眼就看得见 —— 一次实测比十次推测有用。

**绝不写盘**：本地结果只打印，不会覆盖 `structured/<key>.json`。
（精层结果被粗层覆盖是踩坑 #16，那次丢了一批真数据。）
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
from core.cli import flag, pos
from core.config import get_key
from domain import schema
from pipelines import extract

SHOW = ['material_system', 'dynamic_bond_type', 'precursors', 'synthesis_conditions',
        'characterization', 'key_properties', 'self_healing', 'key_finding']


def _one(provider, title, body, si):
    """跑一次抽取（不带自检循环，A/B 要比的是模型本身）。返回 (data, 秒)。"""
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


def _fmt(v, width=300):
    if isinstance(v, (list, tuple)):
        v = '; '.join(str(x) for x in v)
    return str(v).replace('\n', ' ')[:width]


def main():
    key = paths.check_key(pos(0) or '')
    md = paths.fulltext(key)
    if not os.path.exists(md):
        print(f'{key} 没有 parsed/full.md，抽不了')
        return
    meta = {}
    if os.path.exists(paths.meta(key)):
        try:
            meta = json.load(io.open(paths.meta(key), encoding='utf-8'))
        except Exception:
            pass
    title = meta.get('title') or key
    body = schema.hierarchical_body(io.open(md, encoding='utf-8').read())
    si = extract.si_text(key)
    print(f'{title[:70]}\n正文 {len(body)} 字符，SI {len(si)} 字符\n')

    old = None
    if os.path.exists(paths.structured(key)):
        try:
            old = json.load(io.open(paths.structured(key), encoding='utf-8'))
        except Exception:
            pass

    local, t_local = _one('ollama', title, body, si)
    print(f'[本地 {get_key("OLLAMA_MODEL", default="ollama")}] 用时 {t_local}s')
    cloud = None
    if flag('--both'):
        cloud, t_cloud = _one('deepseek', title, body, si)
        print(f'[云端 DeepSeek] 用时 {t_cloud}s')

    print('\n' + '=' * 78)
    for f in SHOW:
        print(f'\n■ {f}')
        print(f'  本地   : {_fmt(local.get(f))}')
        if cloud is not None:
            print(f'  云端   : {_fmt(cloud.get(f))}')
        if old is not None:
            tag = '已有(' + schema.tier_label(old) + ')'
            print(f'  {tag:6s}: {_fmt(old.get(f))}')
    print('\n' + '=' * 78)
    n_local = sum(1 for f in schema.SCHEMA if schema.has_value(local.get(f)))
    print(f'本地填出 {n_local}/{len(schema.SCHEMA)} 个字段有值', end='')
    if old is not None:
        print(f'；已有记录 {sum(1 for f in schema.SCHEMA if schema.has_value(old.get(f)))}/'
              f'{len(schema.SCHEMA)}')
    else:
        print()
    print('（本次不写盘。数字对不上不代表谁对 —— 要看上面每一栏是不是真在原文里）')


if __name__ == '__main__':
    main()
