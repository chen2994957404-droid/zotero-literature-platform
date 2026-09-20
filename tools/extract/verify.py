# -*- coding: utf-8 -*-
"""verify · 数字核对第二道闸：抽出来的每个数，原文**在那个位置、对那个样品**真的这么说了吗。

**为什么有它**（2026-09-20，用户点头）：`audit.py` 是第一道闸 —— 纯字符串比对，免费，
但只能答「这个数在原文里出现过没有」。「16」在引用编号里也算出现；
「Mn = 16 kg/mol」挂在 H85 还是 H90 上它分不出。第二道闸问的是**语义**：
把数字出现处前后各 700 字符切成段落，连同「样品 + 性质 + 值 + 条件」这句主张，
交给 Jev 判断模型（`shared/adapters/typesafe`）判真假。

**为什么是 Jev 不是大模型**：实测（docs/reference/Jev判断模型_实测报告.md）128 条主张
0 条假数放过、22 秒；本地 qwen3.5 同题 349 秒。它的概率校准好：noul ≥ 0.2 的全是真 ——
所以阈值定 0.2，不是 0.5。

结果写回 `structured/<key>.json` 每条 measurement：
    verified      'yes'（原文这么说了）/ 'no'（原文有这个数但不是这么说的）/
                  'unfound'（原文逐字找不到这个数：换算过、或从图上读的、或编的）/
                  'skipped'（个位数，没法定位，不下结论）
    verify_score  Jev 给的 0–1（unfound 时无）
`paperdb` 把 `verified` 带进 measurements 表 —— 「哪些数字能直接写进论文」就是一句 SQL。

**不删、不改数** —— 标出来给人看。低于阈值的可能是抽取错，也可能是段落没切好。

用法：
    python -m tools.extract.verify --key ABCD1234     # 核一篇
    python -m tools.extract.verify --limit 20         # 核最近 20 篇还没核过的
    python -m tools.extract.verify --all              # 全库没核过的（1000 篇约 1 美元以内）
    加 --重新 把核过的也重核
"""
import io
import json
import os
import re
import sys
import time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.kernel import errors, paths
from shared.kernel.cli import flag, opt, wants_help
from shared.kernel.log import get_logger

THRESHOLD = 0.2          # 实测校准：≥0.2 的 53 条 100% 为真；0.5 会把 1/3 的真数误判
WINDOW = 700             # 数字前后各切多少字符
MAX_WINDOWS = 3          # 一个数在原文出现多次时最多带几段（优先带有样品号的）
PURPOSE = 'VERIFY_NUM'
_log = get_logger('extract.verify')

_NUM = re.compile(r'(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\d.])')


def _question():
    from shared.adapters import typesafe
    return typesafe.build_questions(noul={'ok': (
        'Does the passage explicitly report this claim with the same numeric value '
        '(allow rounding of at most 2%) for the same sample and condition?',
        {'true': 'The passage states this quantity with this value for this sample/condition',
         'false': 'The passage gives a different value, attributes it to a different sample, '
                  'or does not report this quantity at all'})})


def claim_text(m):
    """一条 measurement → 一句英文主张（给判断模型看的，机器数据保持英文）。"""
    name = (m.get('name') or 'value').strip()
    sid = (m.get('sample_id') or '').strip()
    cond = (m.get('condition') or '').strip()
    s = name
    if sid and sid.lower() not in ('', 'n/a', 'main'):
        s += f' of sample {sid}'
    if cond and cond.lower() != 'n/a':
        s += f' ({cond})'
    return f'{s} = {(m.get("value_text") or m.get("value") or "").strip()}'


def number_of(m):
    """主张里的主数值（逐字找原文用）。多个数（区间 / 前后对比）取第一个；没有数返回 ''。

    个位数返回 ''（不核）：「Grade 1」的 1 会切到 DOI 尾巴上，「5 h」的 5 在任何长文里都有，
    带着错段落去问只会得到「没说过」（2026-09-20 首批 30 篇抽检发现）。
    """
    nums = [n for n in _NUM.findall(str(m.get('value_text') or m.get('value') or ''))
            if len(n.replace('.', '').replace(',', '')) >= 2]
    return nums[0] if nums else ''


def windows(source, number, sample_id='', n=MAX_WINDOWS, width=WINDOW):
    """原文里这个数的出现处 → 段落列表（去掉空白和千分位后比对，MineRU 常把 1 000 拆开）。

    优先带**含样品号**的段落 —— 同一个数常在引用编号、图片哈希里也出现，
    带错段落会让判断模型说「没说过」（实测里 25 条「误判」有一半是这么来的）。
    """
    if not number or not source:
        return []
    pat = re.compile(r'(?<![\d.])' + re.escape(number).replace(',', r'[,\s]?') + r'(?![\d.])')
    hits = []
    for mt in pat.finditer(source):
        lo, hi = max(0, mt.start() - width), min(len(source), mt.end() + width)
        seg = source[lo:hi]
        has_sid = bool(sample_id) and sample_id.lower() not in ('main', 'n/a') and sample_id.lower() in seg.lower()
        hits.append((0 if has_sid else 1, len(hits), seg))
        if len(hits) >= 12:
            break
    hits.sort()
    return [seg for _, _, seg in hits[:n]]


def verify_record(record, source, ask=None, threshold=THRESHOLD):
    """一条记录 + 原文 → 就地给每条 measurement 标 verified / verify_score，返回统计。

    `ask(state, questions) → {'ok': {'value': float}}` 可注入（自测用假的）；默认走 Jev。
    """
    if ask is None:
        from shared.adapters import typesafe
        ask = lambda state, q: typesafe.ask(state, q, purpose=PURPOSE)
    q = _question()
    stat = {'n': 0, 'yes': 0, 'no': 0, 'unfound': 0}
    for m in record.get('measurements') or []:
        if not isinstance(m, dict):
            continue
        stat['n'] += 1
        num = number_of(m)
        if not num:
            m['verified'] = 'skipped'          # 个位数 / 没有数：没法逐字定位，不下结论
            m.pop('verify_score', None)
            stat['skipped'] = stat.get('skipped', 0) + 1
            continue
        segs = windows(source, num, m.get('sample_id') or '')
        if not segs:
            m['verified'] = 'unfound'
            m.pop('verify_score', None)
            stat['unfound'] += 1
            continue
        state = {'passages': segs, 'claim': claim_text(m)}
        v = float(ask(state, q)['ok']['value'])
        m['verify_score'] = round(v, 3)
        m['verified'] = 'yes' if v >= threshold else 'no'
        stat['yes' if v >= threshold else 'no'] += 1
    return stat


def _source_text(key):
    parts = []
    for p in (paths.fulltext(key), paths.si_fulltext(key)):
        if os.path.exists(p):
            try:
                parts.append(io.open(p, encoding='utf-8').read())
            except Exception:
                continue
    return '\n'.join(parts)


def is_verified(record):
    return bool(record.get('verified_at'))


def verify_one(key, write=True, log=print):
    """核一篇：读记录与原文 → Jev → 写回。没密钥返回 None（调用方照常往下走）。"""
    key = paths.check_key(key)
    p = paths.structured(key)
    if not os.path.exists(p):
        log(f'  [核对跳过] {key} 没有结构化记录')
        return None
    record = json.load(io.open(p, encoding='utf-8'))
    src = _source_text(key)
    if len(src) < 500:
        log(f'  [核对跳过] {key} 没有可比对的原文')
        return None
    try:
        stat = verify_record(record, src)
    except errors.ConfigError as e:
        log(f'  [核对跳过] {e}')
        return None
    except Exception as e:
        log(f'  [核对失败] {key}：{str(e)[:80]}')
        return None
    record['verified_at'] = time.strftime('%Y-%m-%d %H:%M')
    record['verify_model'] = 'jev'
    if write:
        json.dump(record, io.open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    log(f'  [数字核对] {stat["n"]} 个数：原文这么说 {stat["yes"]} · 不是这么说 {stat["no"]} · 原文找不到 {stat["unfound"]}'
        + (f' · 个位数不核 {stat["skipped"]}' if stat.get('skipped') else ''))
    return stat


def _keys(limit=None, redo=False):
    files = [f for f in os.listdir(paths.STRUCTURED) if f.endswith('.json')]
    files.sort(key=lambda f: -os.path.getmtime(os.path.join(paths.STRUCTURED, f)))
    out = []
    for f in files:
        try:
            rec = json.load(io.open(os.path.join(paths.STRUCTURED, f), encoding='utf-8'))
        except Exception:
            continue
        if not redo and is_verified(rec):
            continue
        if not rec.get('measurements'):
            continue
        out.append(f[:-5])
        if limit and len(out) >= limit:
            break
    return out


def main():
    if wants_help():
        print(__doc__)
        return 0
    key = opt('--key')
    if key:
        r = verify_one(key)
        return 0 if r else 1
    lim = opt('--limit')
    if not lim and not flag('--all'):
        print(__doc__)
        return 0
    keys = _keys(limit=int(lim) if lim else None, redo=flag('--重新'))
    print(f'要核 {len(keys)} 篇')
    tot = {'n': 0, 'yes': 0, 'no': 0, 'unfound': 0}
    for i, k in enumerate(keys, 1):
        print(f'{i}/{len(keys)} {k}')
        r = verify_one(k)
        if r is None and not os.path.exists(paths.structured(k)):
            continue
        if r is None:
            return 1                       # 没密钥 / 挂了：别一篇篇继续报同一个错
        for c in tot:
            tot[c] += r[c]
    print(f'合计 {tot["n"]} 个数：原文这么说 {tot["yes"]} · 不是这么说 {tot["no"]} · 原文找不到 {tot["unfound"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
