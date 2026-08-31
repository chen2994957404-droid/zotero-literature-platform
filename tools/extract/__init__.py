# -*- coding: utf-8 -*-
"""extract · 结构化抽取：一篇文献 → 对齐的机器可读字段 → 横向对比表。

用户找研究方向、找空白格的主要依据。抽出来的数据**保持英文原生**，
不翻译（用户本来就读英文文献，这些是给大模型做关联分析的中间产物）。

**对外契约**（别的地方只许调这些；`cli.py` / `mcp.py` 也只许调这些）：

| 入口 | 干什么 |
|---|---|
| `run(key, force) → record`  | **主入口**：抽一篇 + 并入对比表；抽过且字段没升版就跳过 |
| `extract_one(key)`          | 只抽不出表（批量时用，最后统一出一次表） |
| `write_compare_table()`     | 读全部 `structured/*.json` 重出两张表 |
| `all_records()`             | 读回所有已抽记录 |
| `stale_keys()`              | 字段升版后，谁该重抽 |
| `si_pending_keys()`         | 有 SI 却是「没读 SI 时」抽的（花钱前先看这个） |
| `local_keys()`              | 本地模型抽的（值得花钱升级的清单） |
| `si_text(key)` / `backup_records(keys)` | SI 全文 / 覆盖前备份 |
| `batch.extract_many / coarse_all / ensure_fullmd` | 批量三条线 |
| `domain_filter.main`        | 从全库筛出本方向的干净子表 |
| `compare_models.main`       | 本地 vs 云端 A/B（**只打印不写盘**） |
| `wizard.main`               | 给人双击的重抽向导 |

`run()` **不抛异常**：失败返回 None 并记进状态库 ——
抽取失败不该让已经花了钱的精读和回写白做。

它读什么料：正文 `parsed/full.md` **加上** SI `si_parsed/full.md`。
**SI 必须读** —— 投料量、配比、温度时间几乎只写在 SI 里，
不读它 `synthesis_conditions` 就只能是 N/A（2026-08-28 实测：精层也只有 36% 有值）。
哪些篇有 SI 却是「没读 SI 时抽的」→ `si_pending_keys()`，那就是该重抽的清单。

它组合了什么：
    shared.kernel.paths（去哪读、往哪写）
  + shared.domain.schema（抽什么字段、怎么问、怎么摆成表）
  + shared.adapters.llm_client（谁来抽）
  + shared.kernel.jobs（谁抽的、哪版 schema、失败在哪）

**自我评估循环**（借鉴 KnowMat，用自己的公理件实现，不引第三方框架）：
抽完对照原文自检，发现漏抽/幻觉就带着反馈重抽一轮。
`EXTRACT_NO_EVAL=1` 可关掉省钱；本地模型（ollama）自检不可靠，自动跳过。

「加字段之后只重抽缺该字段的那些文献」怎么做到：
    shared.domain.schema.SCHEMA_VER +1 → `jobs.stale('extract', schema_ver=新版本)`
    就是待重抽清单。不用翻文件系统，也不用人肉记得改过什么。
"""
import io
import json
import os

from shared.adapters.llm_client import chat_json as _chat_json
from shared.kernel import jobs, paths
from shared.kernel.config import get_key, get_model
from shared.domain import schema

STEP = 'extract'
PRODUCER = 'extract_structured'

# 自检开关：默认开（质量增强），设 EXTRACT_NO_EVAL=1 关掉省钱
EVAL_ENABLED = os.environ.get('EXTRACT_NO_EVAL', '') != '1'


def _provider():
    """云端 DeepSeek（默认，准）还是本地 Ollama（省钱，质量差一档）。"""
    return os.environ.get('EXTRACT_PROVIDER', 'deepseek').lower()


def _model():
    if _provider() == 'ollama':
        return get_key('OLLAMA_MODEL', default='qwen2.5:7b-instruct')
    return get_model('EXTRACT_MODEL')      # 抽取要准 → pro；可在控制面板切换


def llm_json(system, user):
    """按 provider 分流到公理件。**联网只发生在 adapters 里**（宪法铁律）。"""
    if _provider() == 'ollama':
        return _chat_json(system, user, provider='ollama', model=_model())
    return _chat_json(system, user, provider='deepseek', model=_model(),
                      key=get_key('DEEPSEEK_KEY'))


def evaluate(body, data):
    """对照原文检查抽取结果，返回 {ok, missed, hallucinated}。

    自检失败**不算抽取失败** —— 它只是质量增强，缺了不影响产出。
    """
    try:
        return llm_json(schema.EVAL_SYS, schema.build_eval_prompt(data, body))
    except Exception as e:
        return {'ok': True, 'missed': [], 'hallucinated': [], '_eval_error': str(e)}


def extract_with_eval(title, body, si='', max_cycles=2, log=print):
    """抽取 + 自我评估重抽循环。返回 (data, report)。`si` 为补充材料全文（可空）。"""
    data = llm_json(schema.SYS, schema.build_user_prompt(title, body, si))
    if not EVAL_ENABLED or _provider() == 'ollama':      # 本地模型评估不可靠
        return data, {'ok': None, 'note': 'eval skipped'}
    # 自检也要照着「正文+SI」查，否则 SI 里抽来的投料量会被判成幻觉
    source = body if not si else body + "\n\n[SUPPLEMENTARY INFORMATION]\n" + si
    report = {'ok': None}
    for cycle in range(max_cycles):
        report = evaluate(source, data)
        if report.get('ok') is True or (not report.get('missed')
                                        and not report.get('hallucinated')):
            return data, report
        log(f'  [自检第{cycle+1}轮] 漏抽{len(report.get("missed", []))} '
            f'幻觉{len(report.get("hallucinated", []))}，重抽')
        data = llm_json(schema.SYS,
                        schema.build_user_prompt(title, body, si) + "\n\n"
                        + schema.build_feedback(report))
    return data, report


def si_text(key):
    """这篇的 SI 全文（层次化取过的）；没有 SI 解析产物就返回空串。

    只有跑过 SI 精读的篇才有 `si_parsed/full.md` —— 那一步已经把 PDF/docx
    解析成 Markdown 了，这里**不再花任何钱**，纯读文件。
    """
    p = paths.si_fulltext(key)
    if not os.path.exists(p):
        return ''
    try:
        return schema.si_body(io.open(p, encoding='utf-8').read())
    except Exception:
        return ''          # SI 读不出来不该毁掉整篇抽取，正文照抽


def extract_one(key, log=print):
    """抽一篇，写出 `structured/<key>.json`，返回记录；没有 full.md 则 None。"""
    key = paths.check_key(key)
    md_path = paths.fulltext(key)
    if not os.path.exists(md_path):
        log(f'[跳过] {key} 无 full.md')
        return None
    meta = {}
    if os.path.exists(paths.meta(key)):
        try:
            meta = json.load(io.open(paths.meta(key), encoding='utf-8'))
        except Exception:
            meta = {}
    title = meta.get('title') or key
    body = schema.hierarchical_body(io.open(md_path, encoding='utf-8').read())
    si = si_text(key)
    log(f'[抽取] {title[:50]} …' + (f'（含 SI {len(si)} 字符）' if si else ''))
    data, _report = extract_with_eval(title, body, si, log=log)
    src = schema.SOURCE_LOCAL if _provider() == 'ollama' else schema.SOURCE_FINE
    record = schema.make_record(key, title, meta.get('DOI', ''), data,
                               source=src, si_used=bool(si))
    os.makedirs(paths.STRUCTURED, exist_ok=True)
    json.dump(record, io.open(paths.structured(key), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    return record


def all_records():
    """读回所有已抽取的记录（出表用）。坏文件跳过，不让一个坏 JSON 毁掉整张表。"""
    out = []
    if not os.path.isdir(paths.STRUCTURED):
        return out
    for f in sorted(os.listdir(paths.STRUCTURED)):
        if not f.endswith('.json'):
            continue
        try:
            out.append(json.load(io.open(os.path.join(paths.STRUCTURED, f),
                                         encoding='utf-8')))
        except Exception:
            continue
    return out


def write_compare_table(records=None):
    """出两张表：研究论文对比表 + 综述清单。返回 compare.md 的路径。"""
    records = all_records() if records is None else records
    os.makedirs(paths.STRUCTURED, exist_ok=True)
    io.open(paths.compare(), 'w', encoding='utf-8').write(schema.compare_table(records))
    rev = schema.reviews_table(records)
    if rev:
        io.open(paths.compare('compare_reviews'), 'w', encoding='utf-8').write(rev)
    return paths.compare()


def run(key, force=False, log=print):
    """抽一篇 + 并入对比表。**幂等**：抽过且 schema 没升版就跳过。

    返回记录；跳过时返回已有记录；没 full.md 或失败返回 None（不抛异常）。
    """
    key = paths.check_key(key)
    if not force and jobs.is_done(key, STEP, require='structured',
                                  schema_ver=schema.SCHEMA_VER):
        log(f'  [跳过抽取] {key} 已抽过（schema v{schema.SCHEMA_VER}），不重抽')
        try:
            return json.load(io.open(paths.structured(key), encoding='utf-8'))
        except Exception:
            return None
    try:
        with jobs.track(key, STEP, producer=PRODUCER, model=_model(),
                        schema_ver=schema.SCHEMA_VER):
            rec = extract_one(key, log=log)
            if rec is None:
                raise FileNotFoundError(f'{key} 没有 full.md，抽不了')
    except Exception as e:
        log(f'  [结构化抽取失败] {e}')
        return None
    write_compare_table()
    log('  [结构化抽取完成] 已并入 structured/compare.md')
    return rec


def stale_keys():
    """哪些文献该重抽（schema 升版了，或上次没成功）。"""
    return jobs.stale(STEP, schema_ver=schema.SCHEMA_VER)


def backup_records(keys, stamp=None):
    """覆盖前把这些篇的旧结果整批备份出去。返回备份目录；没东西可备份返回 None。

    踩坑 #16 的代价买来的：曾用低档结果盖掉高档结果，丢了真数据。
    """
    import shutil
    import time as _time
    have = [k for k in keys if os.path.exists(paths.structured(k))]
    if not have:
        return None
    dest = paths.structured_backup(stamp or _time.strftime('%Y%m%d_%H%M%S'))
    os.makedirs(dest, exist_ok=True)
    for k in have:
        shutil.copy2(paths.structured(k), os.path.join(dest, k + '.json'))
    return dest


def local_keys():
    """哪些记录是**本地模型**抽的 —— 以后云端密钥可用时，这就是「值得花钱升级」的清单。"""
    out = []
    for key in paths.all_keys():
        p = paths.structured(key)
        if not os.path.exists(p):
            continue
        try:
            rec = json.load(io.open(p, encoding='utf-8'))
        except Exception:
            continue
        if str(rec.get('source', '')).lower() == schema.SOURCE_LOCAL:
            out.append(key)
    return out


def si_pending_keys():
    """**有 SI，但现有结构化记录是没读 SI 时抽的** —— 值得重抽的清单。

    为什么单独一个清单而不是升 SCHEMA_VER：字段一个没变，
    升版会把 175 篇全判成待重抽（全是钱）。真正缺料的只有这些篇。
    """
    out = []
    for key in paths.all_keys():
        if not os.path.exists(paths.si_fulltext(key)):
            continue
        p = paths.structured(key)
        if not os.path.exists(p):
            continue                       # 还没抽过：走正常抽取流程，不算这一类
        try:
            rec = json.load(io.open(p, encoding='utf-8'))
        except Exception:
            continue
        if not rec.get('si_used'):
            out.append(key)
    return out
