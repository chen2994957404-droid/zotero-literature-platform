# -*- coding: utf-8 -*-
"""chunk_pass · 拆段扫正文里的数值。**模型只做判断，脚本负责把关。**

**为什么要这一条**（2026-09-07 实测）：整篇过一次大模型时，
`schema.hierarchical_body()` 平均只把 9243 字符喂进去，而全文平均 49995 ——
**42 篇无一例外被砍掉一半以上**。模型抽不全不是因为笨，是**没看见**。
表格那条线（`scan.scan_tables`）已经把表里的数捞干净了，正文里的还散着。

**分工**（这是整条线的设计要点）：

| 谁 | 干什么 |
|---|---|
| 脚本 | 切段、挑出有数字的段、给出封闭的样品名单 |
| 模型 | 只回答「这段里哪个数是哪个样品的什么性能」 |
| 脚本 | **逐条验**：数字不在这段里就丢，样品不在名单里就丢，跟表格重了就丢 |

那道校验层是「0.8 GB 的小模型也能用」的全部前提。比武实测
（`python -m tools.extract.bench_chunk`，8 段真实正文）：
云端 `qwen3.5-plus` 抽 31 条、接地 100%、4.1s/段；
本地 `gemma3:1b`（0.8 GB）抽 40 条、接地 94%、样品合法 80%、3.5s/段。
1b 抽得比云端还多，只是会犯两种错 —— **而它犯的那两种错，脚本都能当场判掉**。

用法：
    python -m tools.extract.chunk_pass --key ABCD1234          # 单篇，看结果
    python -m tools.extract.chunk_pass --all --model gemma3:1b # 全库（本地免费）
    python -m tools.extract.chunk_pass --all --limit 5         # 先跑五篇看看
"""
import io
import json
import os
import re
import sys
import time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters import llm_client
from shared.domain import schema
from shared.domain.schema import scan
from shared.kernel import paths, prompts, role
from shared.kernel.cli import flag, opt, wants_help
from shared.kernel.log import get_logger

from .bench_chunk import build_prompt, split_chunks, _sample_list

SYS = prompts.load('extract', 'chunk@v1')
log = get_logger('extract')

_NUM_TOKEN = re.compile(r'\d+(?:\.\d+)?')


def _digits(text):
    """一段文字里的数字（**只数两位及以上**）。

    个位数在任何长文里都必然命中，拿它当「找得到」的证据没有区分度。
    """
    return [t for t in _NUM_TOKEN.findall(str(text or ''))
            if len(t.replace('.', '')) >= 2]


def validate(rows, chunk, samples, table_rows=()):
    """模型这一段的输出 → 留得下的那些。返回 (留下的, 各种理由丢掉的计数)。

    **三条判据，都不需要「理解」，所以都由脚本执行**：

    1. **数字不在这一段里 → 丢。**答案只能来自这一段，不在就是编的。
       （一个例外：`12.0` 这种写法去掉尾零再找一次。）
    2. **样品不在名单里、也不是 unknown → 丢。**名单是脚本从表格与记录里取的，
       模型没有权力发明新样品。
    3. **跟表格扫出来的重了 → 丢。**表格那条带着出处，更硬。

    为什么是丢、而不是留着标记：一条**不知真假**的数值比没有这条更糟 ——
    它会被算进统计、被拿去比大小，而它长得跟真的一模一样。
    """
    src = re.sub(r'[\s,]', '', str(chunk))
    allowed = set(samples) | {'unknown'}
    seen_table = {(t.get('sample_id'), t.get('name'), t.get('value'))
                  for t in table_rows}
    kept = []
    drop = {'编的数字': 0, '编的样品': 0, '没有数值': 0, '跟表格重了': 0}
    for m in rows:
        if not isinstance(m, dict):
            continue
        name = str(m.get('name') or '').strip()
        text = str(m.get('value_text') or '').strip()
        sid = str(m.get('sample_id') or 'unknown').strip() or 'unknown'
        toks = _digits(text)
        if not toks:
            drop['没有数值'] += 1
            continue
        if not all(t in src or t.rstrip('0').rstrip('.') in src for t in toks):
            drop['编的数字'] += 1
            continue
        if sid not in allowed:
            drop['编的样品'] += 1
            continue
        parsed = schema.parse_property(('%s: %s' % (name, text)) if name else text)
        if parsed['value'] is None:
            drop['没有数值'] += 1
            continue
        canon = schema.normalize_property_name(name or parsed['name'])
        if (sid, canon, parsed['value']) in seen_table:
            drop['跟表格重了'] += 1
            continue
        kept.append({
            'sample_id': sid, 'name': canon, 'raw_name': name or parsed['name'],
            'value': parsed['value'], 'value_max': parsed['value_max'],
            'unit': parsed['unit'], 'cmp': parsed['cmp'],
            'condition': str(m.get('condition') or '').strip(),
            'location': scan.nearest_ref(chunk, max(str(chunk).find(toks[0]), 0)),
            'section': 'main', 'method': 'chunk',
            'raw': ('%s: %s' % (name, text)).strip(': ')})
    return kept, drop


def _dedup(rows):
    """同一个「样品 × 性能 × 数值 × 单位」只留一条。

    不同段落复述同一个数是常态（摘要说一遍、讨论再说一遍），
    不去重的话，「这个体系有几个数据点」会被复述次数带偏。
    """
    out, seen = [], set()
    for r in rows:
        k = (r['sample_id'], r['name'], r['value'], r['unit'])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def run_one(key, model=None, max_chunks=0, verbose=True):
    """一篇 → 落一份 `curated/<key>/chunk_measurements.json`。返回统计 dict。"""
    p = paths.fulltext(key)
    if not os.path.exists(p):
        return {'key': key, 'error': '没有 parsed/full.md'}
    md = io.open(p, encoding='utf-8').read()
    rec = {}
    sp = paths.structured(key)
    if os.path.exists(sp):
        try:
            rec = json.load(io.open(sp, encoding='utf-8'))
        except Exception:
            rec = {}
    samples = _sample_list(rec, md)
    table_rows = [t for t in scan.scan_tables(md) if t.get('kind') != 'composition']
    chunks = split_chunks(md)
    if max_chunks:
        chunks = chunks[:max_chunks]

    kept_all, drops = [], {}
    n_fail = 0
    t0 = time.time()
    for i, ch in enumerate(chunks, 1):
        try:
            data = llm_client.chat_json(SYS, build_prompt(ch, samples),
                                        model=model, num_ctx=8192)
        except Exception as e:
            n_fail += 1
            log.warning('%s 第 %d 段失败：%s', key, i, str(e)[:120])
            continue
        rows = (data or {}).get('measurements')
        if not isinstance(rows, list):
            n_fail += 1
            continue
        kept, drop = validate(rows, ch, samples, table_rows)
        kept_all += kept
        for k, v in drop.items():
            drops[k] = drops.get(k, 0) + v
    kept_all = _dedup(kept_all)

    out = {'key': key, 'model': model or '', 'n_chunks': len(chunks),
           'n_failed_chunks': n_fail, 'measurements': kept_all,
           'dropped': drops, 'secs': round(time.time() - t0, 1)}
    if chunks:
        paths.parsed_dir(key)                     # 保证 curated/<key>/ 在
        io.open(paths.chunk_measurements(key), 'w', encoding='utf-8').write(
            json.dumps(out, ensure_ascii=False, indent=1))
    if verbose:
        shown = '、'.join('%s %d' % kv for kv in sorted(drops.items()) if kv[1])
        print('%s  %2d 段 → 留下 %3d 条（脚本判掉：%s）%.0fs'
              % (key, len(chunks), len(kept_all), shown or '无', out['secs']))
    return out


def _keys_with_fulltext():
    return [k for k in paths.all_keys() if os.path.exists(paths.fulltext(k))]


def main():
    if wants_help():
        print(__doc__)
        return
    model = opt('--model') or None
    key = opt('--key')
    if key:
        run_one(key.upper(), model=model, max_chunks=int(opt('--chunks', 0)))
        return
    if not flag('--all'):
        print('要么给 --key <KEY> 跑一篇，要么给 --all 跑全库。--help 看用法。')
        return
    # 全库作业：几百次模型请求。本地模型不花钱，云端会花 —— 都按全库作业对待。
    role.require_prod('全库拆段抽取（几百次模型请求）', force=flag('--force'))
    keys = _keys_with_fulltext()
    limit = int(opt('--limit', 0))
    if limit:
        keys = keys[:limit]
    print('拆段抽取 %d 篇，模型 %s\n' % (len(keys), model or '（配置里的默认）'))
    n_kept = n_drop = 0
    for k in keys:
        r = run_one(k, model=model)
        n_kept += len(r.get('measurements') or [])
        n_drop += sum((r.get('dropped') or {}).values())
    print('\n合计留下 %d 条，脚本判掉 %d 条' % (n_kept, n_drop))


if __name__ == '__main__':
    main()
