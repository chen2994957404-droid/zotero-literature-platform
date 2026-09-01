# -*- coding: utf-8 -*-
"""deepread/evals · 精读质量评测集（一份精读 → 可比较的质量记录）

**为什么需要它**：平台的体检全在验「能不能跑」，**没有一项在验「跑出来的东西好不好」**——
而后者才是用户真正在乎的。那次「只贴了图没有文字」的废品，是用户自己翻到的，
不是系统报的。后来加的 `MIN_OK` 只是单点防护：挡得住「没字」，挡不住「字很多但都是废话」。

## 目的不是攒分数

单纯收集「好/差」用处有限 —— 改完精读逻辑重跑后，没人给新版本打分，
评测集会变成一次性的。

**真正的价值是：用用户的主观评分，校准出一个系统能自动算的质量分。**
所以每条评价都连同当时精读的**客观快照**一起记（字数/图数/数值密度/章节完整性）。
等样本够了（阈值见 `thresholds.toml`），就能分析「他说好的」和「他说差的」
在客观指标上差在哪，从此系统能自己判断质量退化，不用等人翻到。

## 为什么在这里（R5 窗从 shared/adapters/evalset 搬来）

它只服务 deepread 一个工具，而 `shared/` 的准入门槛是「被 ≥2 个工具用到」。
而且它根本不是 adapter —— 它不联网、不包装任何外部服务，
它是**「怎么评价这个工具的产出」**，那正是 `tools/<t>/evals/` 的定义。

对外接口：
  - snapshot(key)            → 某篇精读的客观指标快照（评分器在 scorers/quality.py）
  - save(key, verdict, ...)  → 记录一条评价（含快照）
  - load() / get(key) / remove(key)
  - pending(read_keys)       → 「读完了但还没评价」的清单
  - stats()                  → 好/差各多少、客观指标的差异、还差几篇才够校准；
                              `stale` 列出用旧口径算的快照
  - recompute()              → 按当前口径重算所有快照（改了 METRICS_VER 就跑一次）
  - REASONS                  → 差评原因选项（面板上给用户勾）
  - THRESHOLDS               → thresholds.toml 的内容
"""
import json
import os
import time
import tomllib

from shared.kernel import paths
from tools.deepread.evals.scorers import quality

EVALSET = paths.evalset()

_TOML = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'thresholds.toml')
with open(_TOML, 'rb') as _f:
    THRESHOLDS = tomllib.load(_f)

MIN_GOOD = THRESHOLDS['calibration']['min_good']
MIN_BAD = THRESHOLDS['calibration']['min_bad']

# 差评原因选项（用户在面板上勾选；以后从样本里归纳新的类别）
REASONS = [
    ('missing_data', '缺关键数据（没有具体数值/条件）'),
    ('too_vague', '太笼统，没有信息量'),
    ('figure_bad', '图不对、缺图、或图文不搭'),
    ('mechanism_wrong', '机理讲错了'),
    ('structure_bad', '结构混乱、重复啰嗦'),
    ('truncated', '明显被截断，没写完'),
]


def snapshot(key):
    """算一份精读的客观指标。**没有就返回 None，不抛异常**。

    指标怎么算见 `scorers/quality.py`。key 不合法也返回 None ——
    调用方（面板、`save()`）拿到的是「Zotero 里的一批条目」，
    里头混进一个怪 key 不该让整个待评价列表崩掉。
    （搬家前这里是自己拼路径、天然不校验；改走 `paths.summary()` 后
    要把这个宽容显式写出来，否则就是偷偷改了行为。）
    """
    try:
        p = paths.summary(key)
    except paths.BadKeyError:
        return None
    return quality.snapshot_file(p)


def recompute(log=print):
    """按当前口径重算所有已存快照。返回 (重算成功数, 文件已不在的数)。

    **什么时候要跑**：`scorers/quality.py` 的 `METRICS_VER` 一变就跑一次。
    口径改了而不重算，`evalset.json` 里就同时躺着两把尺子量出来的数 ——
    校准会安静地建立在错误的基础上，**不会有任何报错**。

    精读 HTML 还在盘上就能原地重算，所以这件事是零成本的（不调模型、不花钱）。
    文件已经不在的（B 机重建过、或条目被删了），保留旧快照并原样报出来 ——
    宁可让人看见「这几条是旧口径」，也不要偷偷丢掉用户一条条打出来的评价。
    """
    data = load()
    done = missing = 0
    for key, v in data.items():
        if not v.get('snapshot'):
            continue
        fresh = snapshot(key)
        if fresh is None:
            missing += 1
            log(f'  [{key}] 精读 HTML 已不在，保留旧口径快照')
            continue
        v['snapshot'] = fresh
        done += 1
    if done:
        _write(data)
    log(f'重算完成：{done} 条已更新到口径 v{quality.METRICS_VER}'
        + (f'，{missing} 条文件不在' if missing else ''))
    return done, missing


def load():
    if not os.path.exists(EVALSET):
        return {}
    try:
        with open(EVALSET, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _write(data):
    tmp = EVALSET + '.tmp'
    os.makedirs(os.path.dirname(EVALSET), exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, EVALSET)      # 原子替换，避免写一半损坏评测集


def get(key):
    return load().get(key)


def save(key, verdict, reasons=None, note='', title=''):
    """记录一条评价。verdict: 'good' / 'bad'。

    **同时存下当时的客观快照** —— 这是关键：没有快照，评分就只是一个孤立的分数；
    有了快照，才能回答「什么样的客观特征对应着用户认为的好」。
    """
    if verdict not in ('good', 'bad'):
        raise ValueError("verdict 只能是 'good' 或 'bad'")
    data = load()
    data[key] = {
        'verdict': verdict,
        'reasons': list(reasons or []),
        'note': (note or '').strip()[:500],
        'title': title[:120],
        'snapshot': snapshot(key),
        'rated_at': time.strftime('%Y-%m-%d %H:%M'),
    }
    _write(data)
    return data[key]


def remove(key):
    data = load()
    if key in data:
        del data[key]
        _write(data)
        return True
    return False


def pending(read_keys):
    """「已读完但还没评价」的 key 列表。read_keys 来自 Zotero 的「读完」标签。"""
    done = load()
    return [k for k in read_keys if k not in done]


def stats():
    """好/差各多少，以及两组在客观指标上的差异。

    这是「用主观评分校准自动指标」的第一步 ——
    差异明显的指标，才是能拿来自动判质量的候选。

    `need_good` / `need_bad` 是「还差几篇才够校准」，**由这里算、不由调用方算** ——
    否则面板、交接生成器各自把阈值 3 硬编码一遍，改阈值就得满仓库找。
    """
    data = load()
    good = [v['snapshot'] for v in data.values()
            if v.get('verdict') == 'good' and v.get('snapshot')]
    bad = [v['snapshot'] for v in data.values()
           if v.get('verdict') == 'bad' and v.get('snapshot')]

    def avg(rows, field):
        vals = [r.get(field) or 0 for r in rows]
        return round(sum(vals) / len(vals), 1) if vals else None

    fields = ('chars', 'figures', 'numbers', 'sections')
    compare = {f: {'good': avg(good, f), 'bad': avg(bad, f)} for f in fields}

    # 差评原因统计：出现最多的，就是精读最该改进的地方
    reason_count = {}
    for v in data.values():
        for r in v.get('reasons') or []:
            reason_count[r] = reason_count.get(r, 0) + 1

    # 口径混着就不该直接拿去校准 —— 两把尺子量出来的数放在一起比，
    # 差异可能全是口径造成的。这里只**报出来**，不擅自丢弃任何一条评价。
    stale = sorted(k for k, v in data.items()
                   if v.get('snapshot')
                   and v['snapshot'].get('metrics_ver', 1) != quality.METRICS_VER)

    need_good, need_bad = max(0, MIN_GOOD - len(good)), max(0, MIN_BAD - len(bad))
    return {
        'total': len(data), 'good': len(good), 'bad': len(bad),
        'compare': compare,
        'reasons': sorted(reason_count.items(), key=lambda x: -x[1]),
        'need_good': need_good, 'need_bad': need_bad,
        'min_good': MIN_GOOD, 'min_bad': MIN_BAD,
        'ready': need_good == 0 and need_bad == 0,   # 样本够不够做校准
        'metrics_ver': quality.METRICS_VER,
        'stale': stale,        # 这些快照是旧口径算的，跑 evals.recompute() 可以刷齐
    }
