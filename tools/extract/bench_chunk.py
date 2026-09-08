# -*- coding: utf-8 -*-
"""bench_chunk · 段落级抽取的模型比武。**五个指标全自动，不靠人看。**

**为什么要它**（2026-09-07，用户拍板前的调研）：
现在一篇文献只有 18% 的正文喂给了模型（实测 42 篇：全文均 49995 字符，
喂进去 9243）。要覆盖全篇就得**拆段处理**，而拆段之后每次输入很短、
选项封闭 —— 那正是小模型可能够用的场合。够不够用不能猜，得比。

**任务**（跟将来真跑的一模一样）：给一段正文 + 这篇的样品名单（封闭选项），
让模型把这段里的测量列出来，每条挂到名单里的某个样品或 "unknown"。

**五个指标，全部不需要人工标注**：

| 指标 | 怎么算 | 它在防什么 |
|---|---|---|
| JSON 可解析率 | 解得出就算 | 小模型最常见的失败是格式崩 |
| 数字接地率 | 输出里每个数字回**这一段**逐字找 | **编数字** |
| 样品合法率 | sample_id 必须在名单里或 unknown | **编样品名** |
| 召回 | 对上脚本在这段扫出的「数值+单位」 | 漏抽 |
| 秒/段 | 计时 | 能不能跑得起量 |

段落级比整篇好验的地方：**答案只能来自这一段**，所以接地率是硬判据，
不像整篇比对那样会被「它在别处见过这个数」蒙混过去。

用法：
    python -m tools.extract.bench_chunk --models qwen3.5:4b,phi4-mini --chunks 12
    python -m tools.extract.bench_chunk --models qwen3.8-flash --chunks 12   # 云端做参照
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
from shared.kernel import paths, prompts
from shared.kernel.cli import opt

SYS = prompts.load('extract', 'chunk@v1')
_NUM_TOKEN = re.compile(r'\d+(?:\.\d+)?')


# 不该喂给模型的段落：参考文献、致谢、作者信息、投稿信息。
# 它们数字很多（年份、卷期、页码），靠数字判据挡不住，只能靠标题。
_SKIP_SECTION = re.compile(
    r'(?i)^#{0,4}\s*(references|bibliography|acknowledg|author\s+information|notes|supporting\s+information|associated\s+content|conflicts?\s+of\s+interest|\(\d+\)\s+[A-Z][a-z]+,)')
# 两位以上的数字（个位数在长文里必然命中，没有区分度）
_LOOSE_NUM = re.compile(r'(?<![\w.])\d{2,}(?:\.\d+)?|(?<![\w.])\d+\.\d+')


def split_chunks(md, target=2400, min_numbers=2):
    """按章节切段，太长的再切；**只留含 ≥2 个「数值+单位」的段**。

    为什么按章节切：MineRU 的 markdown 保着标题层级，那是作者自己划的语义边界 ——
    比按字数硬切好，因为一个测量的名字、条件、数值通常在同一节里。
    没有数字的段不用喂模型（省下的就是钱），脚本判得出来。
    """
    # **先把 LaTeX 洗掉再切**（2026-09-08，踩坑 #143）：不洗的话
    # `$10^{-10}\;\mathrm{M}$` 这种压根不被认成数字，下面那句「这段有没有 ≥2 个数」
    # 就会把整段判成没数字丢掉 —— 模型连看都没看见。洗完还顺带让模型读起来更省劲。
    md = scan.clean_body(md)
    parts = re.split(r'(?m)^(#{1,4}\s+.*)$', md)
    blocks, buf = [], ''
    for seg in parts:
        if not seg.strip():
            continue
        if re.match(r'^#{1,4}\s', seg):
            if buf.strip():
                blocks.append(buf)
            buf = seg + '\n'
        else:
            buf += seg
        while len(buf) > target * 1.8:          # 一节太长就切开，别硬塞
            cut = buf.rfind('\n', 0, target)
            cut = cut if cut > target // 2 else target
            blocks.append(buf[:cut])
            buf = buf[cut:]
    if buf.strip():
        blocks.append(buf)
    out = []
    for b in blocks:
        b = b.strip()
        if len(b) < 200 or _SKIP_SECTION.search(b[:80]):
            continue
        # **选段用「宽松数字」，不用 `scan_numbers`**（2026-09-08，踩坑 #143）：
        # `scan_numbers` 要「数字 + 认得的单位」才算数，于是 `10^-10 M`
        # （M 不在单位词表里）整段被判成「没有数字」丢掉 —— 模型连看都没看见。
        #
        # 判据换成「两位以上的数字出现 ≥2 次」。**这里要往宽了错**：
        # 多喂一段的代价是几厘钱，漏喂一段的代价是那一段的数据永远不存在。
        # 参考文献那类全是数字的段落，靠上面的标题判据挡掉，不靠数字判据。
        if len(_LOOSE_NUM.findall(b)) >= min_numbers:
            out.append(b[:target * 2])
    return out


def _sample_list(rec, md):
    """这篇的样品名单：记录里的 + 脚本从表格拿到的（表格里的行首最准）。"""
    names = [s['sample_id'] for s in schema.samples_of(rec)
             if s['sample_id'] and s['sample_id'] != 'main']
    for t in scan.scan_tables(md):
        if t['sample_id'] and t['sample_id'] not in names:
            names.append(t['sample_id'])
    return names[:40]


def build_prompt(chunk, samples):
    return ('Sample names used in this paper:\n%s\n\n'
            '===== PASSAGE START =====\n%s\n===== PASSAGE END =====' %
            ('\n'.join('  - %s' % s for s in samples) or '  (none given)', chunk))


def score(data, chunk, samples):
    """一次输出 → 四个数（第五个是耗时，在外面记）。"""
    if not isinstance(data, dict):
        return None
    ms = data.get('measurements')
    if not isinstance(ms, list):
        return None
    src = re.sub(r'[\s,]', '', chunk)
    allowed = set(samples) | {'unknown', ''}
    nums = ok_nums = 0
    sid_ok = sid_total = 0
    values = []
    for m in ms:
        if not isinstance(m, dict):
            continue
        sid_total += 1
        if str(m.get('sample_id') or '') in allowed:
            sid_ok += 1
        text = '%s %s' % (m.get('name') or '', m.get('value_text') or '')
        for tok in _NUM_TOKEN.findall(str(m.get('value_text') or '')):
            if len(tok.replace('.', '')) < 2:
                continue
            nums += 1
            if tok in src:
                ok_nums += 1
        values.append(text.strip())
    # 召回：脚本在这段扫出的、认得出性能名的数值，模型报了几个
    want = {str(c['value']) for c in scan.scan_measurements(chunk) if c['value'] is not None}
    got = set()
    for v in values:
        for tok in _NUM_TOKEN.findall(v):
            got.add(str(float(tok)) if '.' in tok else str(float(int(tok))))
    hit = sum(1 for w in want if w in got)
    return {'n': len(ms), 'nums': nums, 'grounded': ok_nums,
            'sid_ok': sid_ok, 'sid_total': sid_total,
            'want': len(want), 'recall_hit': hit}


def collect(n_chunks):
    """挑测试段：从有 v3 记录、且有全文的篇里取，按篇轮流拿，别全来自一篇。"""
    picked = []
    files = sorted(f for f in os.listdir(paths.STRUCTURED) if f.endswith('.json'))
    pool = []
    for f in files:
        try:
            rec = json.load(io.open(os.path.join(paths.STRUCTURED, f), encoding='utf-8'))
        except Exception:
            continue
        key = rec.get('key') or ''
        try:
            p = paths.fulltext(key)
        except paths.BadKeyError:
            continue
        if not os.path.exists(p) or int(rec.get('schema_ver') or 1) < 3:
            continue
        md = io.open(p, encoding='utf-8').read()
        chunks = split_chunks(md)
        if chunks:
            pool.append((key, _sample_list(rec, md), chunks))
    i = 0
    while len(picked) < n_chunks and pool:
        for key, samples, chunks in list(pool):
            if i < len(chunks):
                picked.append((key, samples, chunks[i]))
                if len(picked) >= n_chunks:
                    break
        i += 1
        if i > 8:
            break
    return picked


def run(models, n_chunks=12):
    cases = collect(n_chunks)
    if not cases:
        print('没有可用的测试段（需要 schema v3 的记录 + parsed/full.md）')
        return
    print('测试段 %d 个，来自 %d 篇；样品名单由脚本从表格与记录里取\n'
          % (len(cases), len({c[0] for c in cases})))
    for model in models:
        agg = {'json_ok': 0, 'n': 0, 'nums': 0, 'grounded': 0, 'sid_ok': 0,
               'sid_total': 0, 'want': 0, 'recall_hit': 0, 'secs': 0.0, 'fail': 0}
        for key, samples, chunk in cases:
            t = time.time()
            try:
                data = llm_client.chat_json(SYS, build_prompt(chunk, samples),
                                            model=model, num_ctx=8192)
            except Exception as e:
                agg['fail'] += 1
                agg['secs'] += time.time() - t
                print('   [失败] %s %s' % (key, str(e)[:60]))
                continue
            agg['secs'] += time.time() - t
            s = score(data, chunk, samples)
            if not s:
                continue
            agg['json_ok'] += 1
            for k in ('n', 'nums', 'grounded', 'sid_ok', 'sid_total', 'want', 'recall_hit'):
                agg[k] += s[k]
        tot = len(cases)
        print('%-18s JSON %2d/%2d  抽出%3d条  数字接地 %3d/%3d(%3.0f%%)  '
              '样品合法 %3d/%3d(%3.0f%%)  召回 %3d/%3d(%3.0f%%)  %5.1fs/段'
              % (model, agg['json_ok'], tot, agg['n'],
                 agg['grounded'], agg['nums'], 100.0 * agg['grounded'] / max(agg['nums'], 1),
                 agg['sid_ok'], agg['sid_total'], 100.0 * agg['sid_ok'] / max(agg['sid_total'], 1),
                 agg['recall_hit'], agg['want'], 100.0 * agg['recall_hit'] / max(agg['want'], 1),
                 agg['secs'] / tot))


def main():
    ms = opt('--models') or 'qwen3.5:latest'
    run([m.strip() for m in ms.split(',') if m.strip()],
        n_chunks=int(opt('--chunks', 12)))


if __name__ == '__main__':
    main()
