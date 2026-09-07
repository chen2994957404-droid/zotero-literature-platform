# -*- coding: utf-8 -*-
"""audit · 抽检：抽出来的数字，回原文逐字找得到吗。**不花钱、不联网。**

**为什么有它**（2026-09-07，用户拍板）：原先每篇都跑一轮「自检」——
让模型对照原文自查漏抽与幻觉。它有用，但**代价是把整篇原文再发一遍**，
一篇的花销直接乘三，而抓到的多半是小漏抽。用户说得直接：
「要循环这么多遍吗，如果质量稳定没问题的话抽检一下就行吧。」

于是把「每篇都花钱自检」换成「全库免费抽检 + 人看最差的几篇」：

  · `number_grounding` 是纯字符串比对：抽出来的每个数字，在原文里逐字找一遍
  · 找不到的挑出来 —— 要么是单位换算（1.5×10^4 vs 15000），要么是**编的**
  · 免费、秒级、能覆盖全库；模型自检做不到全库，因为那要花钱

**这是粗判据，不是判决**：换算、把 90% 写成 0.9 都会算成「没找到」。
所以看的是**排序**（谁最不像话）和**具体是什么**，一眼就能分出换算还是瞎编。

还顺带查一条结构性的错：`measurements` 里的 `sample_id` 有没有对应的样品 ——
挂在不存在的样品上的数字，等于没挂。

用法：
    python -m tools.extract.audit                # 全库抽检，按可疑程度排序
    python -m tools.extract.audit --limit 5      # 只看最可疑的 5 篇
    python -m tools.extract.audit --key ABCD1234 # 只看某一篇，列出可疑数字
"""
import io
import json
import os
import sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.domain import schema
from shared.kernel import paths
from shared.kernel.cli import opt


def _source_text(key):
    """这篇的原文（正文 + SI）。没有解析产物就返回空串。"""
    parts = []
    for p in (paths.fulltext(key), paths.si_fulltext(key)):
        if os.path.exists(p):
            try:
                parts.append(io.open(p, encoding='utf-8').read())
            except Exception:
                continue
    return '\n'.join(parts)


def audit_one(record):
    """一条记录 → 抽检结果 dict；没有原文可比时返回 None（不算它对也不算它错）。"""
    key = record.get('key') or ''
    try:
        src = _source_text(key)
    except paths.BadKeyError:
        return None                    # 方向层的记录（OpenAlex id）没有本地原文
    if len(src) < 500:
        return None
    ms = schema.iter_measurements(record)
    hit, total, miss = schema.number_grounding(
        {'m': [m['raw'] for m in ms]}, src)
    fields = {k: v for k, v in record.items()
              if k in schema.SCHEMA and k != 'key_properties'}
    fhit, ftotal, fmiss = schema.number_grounding(fields, src)
    sample_ids = {s['sample_id'] for s in schema.samples_of(record)}
    orphan = sorted({m['sample_id'] for m in ms
                     if m['sample_id'] not in sample_ids})
    return {'key': key, 'title': (record.get('title') or '')[:50],
            'model': record.get('model') or '', 'tier': schema.tier_label(record),
            'n': total, 'hit': hit, 'miss': miss,
            'rate': (hit / total) if total else 1.0,
            'field_rate': (fhit / ftotal) if ftotal else 1.0, 'field_miss': fmiss,
            'orphan': orphan}


def audit_all(records=None):
    """全库抽检，按「命中率低 → 数字多」排序（最可疑的排前面）。"""
    if records is None:
        records = []
        for f in sorted(os.listdir(paths.STRUCTURED)):
            if f.endswith('.json'):
                try:
                    records.append(json.load(io.open(
                        os.path.join(paths.STRUCTURED, f), encoding='utf-8')))
                except Exception:
                    continue
    out = [r for r in (audit_one(x) for x in records) if r]
    return sorted(out, key=lambda r: (r['rate'], -r['n']))


def main():
    """命令行入口。只读文件，不联网、不花钱。"""
    key = opt('--key')
    if key:
        p = paths.structured(key)
        if not os.path.exists(p):
            print('没有这篇的结构化记录：%s' % p)
            return 1
        r = audit_one(json.load(io.open(p, encoding='utf-8')))
        if not r:
            print('这篇没有可比对的原文（没解析过，或原文太短）')
            return 0
        print('%s %s（%s，%s）' % (r['key'], r['title'], r['tier'], r['model'] or '模型未记'))
        print('  数值回原文命中 %d/%d（%.0f%%）' % (r['hit'], r['n'], r['rate'] * 100))
        for x in r['miss']:
            print('    找不到：%s' % x)
        if r['orphan']:
            print('  挂在不存在的样品上：%s' % '、'.join(r['orphan']))
        return 0

    rows = audit_all()
    if not rows:
        print('没有可抽检的记录（要有 parsed/full.md 才比得了）')
        return 0
    lim = int(opt('--limit', 12))
    n_all = sum(r['n'] for r in rows)
    hit_all = sum(r['hit'] for r in rows)
    bad = [r for r in rows if r['rate'] < 0.9]
    orphans = [r for r in rows if r['orphan']]
    print('抽检 %d 篇：数值总数 %d，回原文找得到 %d（%.1f%%）'
          % (len(rows), n_all, hit_all, 100.0 * hit_all / max(n_all, 1)))
    print('命中率低于 90%% 的有 %d 篇；有「挂在不存在样品上」的 %d 篇\n'
          % (len(bad), len(orphans)))
    print('%-10s %-6s %-16s %5s %6s  %s' % ('key', '命中', '模型', '数值', '字段', '标题'))
    print('-' * 96)
    for r in rows[:lim]:
        print('%-10s %5.0f%% %-16s %5d %5.0f%%  %s'
              % (r['key'], r['rate'] * 100, r['model'][:16], r['n'],
                 r['field_rate'] * 100, r['title']))
    if len(rows) > lim:
        print('…还有 %d 篇（--limit 调）' % (len(rows) - lim))
    print('\n看某一篇具体哪些数字对不上：python -m tools.extract.audit --key <KEY>')
    print('⚠ 找不到 ≠ 编的：单位换算（1.5×10^4 vs 15000）、把 90% 写成 0.9 都会算成没找到。')
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
