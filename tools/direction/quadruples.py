# -*- coding: utf-8 -*-
"""quadruples · 方向层：上万条摘要 → 「策略/结构 → 性能 → 应用 → 谁做的」。

**用户要的是什么**（2026-08-29 原话）：「我想了解的是真正的行业动态和方向。
比如抗冲击这块，有哪些人做了什么，用了什么方法，能实现哪些效果和应用。」
——这是方向层，不是细节层：不问怎么合成，只问谁用什么办法做到了什么。

**为什么方向层只用摘要就够**（2026-08-29 实测 200 篇）：付费墙论文
**100% 都有摘要**（OpenAlex 对它们同样提供）。开放获取偏倚咬的是全文，
不是元数据 —— 所以方向层可以覆盖整个领域，合法、免费、不用 PDF。
只有细节层（配方、投料量）才卡在全文上。

**产物落进同一个三层库**（2026-09-07 用户拍板）：一篇摘要 → 一条记录
（`serving/abstracts/<Wxxx>.json`），格式与全文抽取**完全一样**：
论文级字段 + `samples`（一个策略一个样品）+ `measurements`（一个数字一条）。
`source='abstract'` → `tier='摘要'`，于是 `tools/paperdb` 里
「摘要档的 synthesis_conditions 是空的」一眼看得出是**料本来就薄**，不是没抽到。

这也正是「方向层的空白格能指出哪些值得花钱升成细节层」的由来：
同一张表里，某个策略只有摘要档、却反复出现好数字 —— 那就是该去取全文的。

**这是唯一要花钱的一步**：一篇摘要一次小模型调用。所以：
  · 先 `--limit 50` 实测单价，再决定跑多少（架构准则：先算再花）
  · 默认用便宜的那档模型（`DIRECTION_QUAD_MODEL`，默认 qwen3.8-flash）
  · 抽过的不重抽（产物在盘上就跳过），断了随时接着跑

用法：
    python -m tools.direction quads --band impact --limit 50     # 先试 50 条
    python -m tools.direction quads --band impact                # 这条窄带全跑
    python -m tools.direction quads --band impact --list         # 只看还剩多少，不花钱
    python -m tools.direction quads --band impact --all          # 连引用层一起抽（贵得多，多是无关的通用论文）
    python -m tools.direction quads --band impact --models qwen3.8-flash,qwen3.6-flash
                                                                 # 一个模型的免费额度用完就换下一个
"""
import io
import json
import os
import sqlite3
import sys
import time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters import llm_client, openalex
from shared.domain import schema
from shared.kernel import paths, prompts, role
from shared.kernel.cli import flag, opt
from shared.kernel.config import get_model

SYS = prompts.load('direction', 'quad@v1')
BATCH_ABSTRACTS = 50          # 一次问 OpenAlex 要多少篇摘要
ABSTRACT_MIN = 200            # 太短的摘要（其实是标题重复）不值得花钱


def _model():
    """方向层用便宜那档：一篇摘要输出很短，但要跑上万篇。"""
    return get_model('DIRECTION_QUAD_MODEL')


def _build_prompt(title, abstract, venue='', year=''):
    """摘要 → 提问。字段清单跟全文抽取同一套（`shared.domain.schema`）。"""
    meta = ' | '.join(str(x) for x in (venue, year) if x)
    return (
        'Paper title: %s\n%s\n\n' % (title, ('Published in: ' + meta) if meta else '')
        + 'Return ONE JSON object with these three parts.\n\n'
          'PART 1 - paper-level fields:\n'
        + '\n'.join('  - "%s": %s' % (k, v) for k, v in schema.SCHEMA.items())
        + '\n\nPART 2 - "samples": one entry per material/strategy the abstract names. Fields:\n'
        + '\n'.join('  - "%s": %s' % (k, v) for k, v in schema.SAMPLE_SCHEMA.items())
        + '\n\nPART 3 - "measurements": one entry per number printed in the abstract. Fields:\n'
        + '\n'.join('  - "%s": %s' % (k, v) for k, v in schema.MEAS_SCHEMA.items())
        + '\n\nThe abstract is all you have. Leave "location" empty for every measurement, '
          'and set "section" to "abstract".\n\n'
          '===== ABSTRACT START =====\n%s\n===== ABSTRACT END =====' % abstract)


# 「这个模型的免费额度用完了」长什么样（2026-09-07 实测百炼原话）：
#   HTTP 403 ... "Free quota exhausted. To continue accessing the model on a paid
#   basis, please add funds or disable the \"use free tier only\" mode"
# 百炼的免费额度**按模型各算 100 万**，所以这不是「没钱了」，是「这个模型用完了」——
# 换一个还有额度的接着跑就行。认它靠的是这句话本身，不是状态码：
# 403 还可能是密钥不对，那种换模型也没用，得让它照常报错。
_QUOTA_MARKS = ('free quota exhausted', 'allocationquota', 'insufficient_quota')


def is_quota_exhausted(err):
    """这个异常是不是「这个模型的免费额度用完了」。"""
    t = str(err).lower()
    return any(m in t for m in _QUOTA_MARKS)


def pending(band, limit=None, seeds_only=True):
    """这条窄带里还没抽过摘要的作品：`[(id, doi, title, venue, year), ...]`。

    判据是产物在不在盘上 —— **不另记台账**：台账会和文件不同步，
    而文件本身就是真相（跟 paperdb「库是索引不是真相」同一条道理）。

    **默认只抽种子层**（`seeds_only=True`，2026-09-07 实测后改的）：
    `works` 表里还有引用层 —— 种子引到的一切，包括 PBE 泛函这种
    「谁都引一下」的通用方法论文。impact 窄带 12085 篇里种子只有 2328 篇，
    剩下的大多跟抗冲击没关系。给它们花钱是纯浪费，而且会把方向层的版图冲淡。
    真要连引用层一起抽，`seeds_only=False`。
    """
    c = sqlite3.connect(paths.direction_db(band))
    try:
        sql = 'SELECT id, doi, title, venue, year FROM works '
        if seeds_only:
            sql += 'WHERE is_seed = 1 '
        rows = c.execute(sql + 'ORDER BY cited_by DESC').fetchall()
    finally:
        c.close()
    out = []
    for wid, doi, title, venue, year in rows:
        try:
            p = paths.abstract_record(wid)
        except paths.BadKeyError:
            continue
        if os.path.exists(p):
            continue
        out.append((paths.check_work_id(wid), doi or '', title or '', venue or '', year))
        if limit and len(out) >= limit:
            break
    return out


def _abstracts(work_ids):
    """一批作品 id → `{短id: 摘要正文}`（OpenAlex 的倒排索引还原成人话）。"""
    got = openalex.works_by_ids(list(work_ids), allow_partial=True)
    out = {}
    for short, w in got.items():
        text = openalex.restore_abstract(w.get('abstract_inverted_index'))
        if text and len(text) >= ABSTRACT_MIN:
            out[short] = text
    return out


def one(work_id, title, abstract, doi='', venue='', year='', model=None):
    """一篇摘要 → 记录（已落盘）。返回记录；模型没给出东西时返回 None。"""
    data = llm_client.chat_json(
        SYS, _build_prompt(title, abstract, venue, year),
        model=model or _model(), key=None)
    if not isinstance(data, dict) or not data:
        return None
    # 摘要天然没有出处，模型若硬填也在这里被 schema 的 clean_location 洗掉
    for m in (data.get('measurements') or []):
        if isinstance(m, dict):
            m['section'] = 'abstract'
    rec = schema.make_record(paths.check_work_id(work_id), title, doi, data,
                             source=schema.SOURCE_ABSTRACT, si_used=False,
                             model=model or _model())
    rec['venue'] = venue
    rec['year'] = year
    p = paths.abstract_record(work_id)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(rec, io.open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    return rec


def run(band, limit=None, log=print, seeds_only=True, models=None):
    """跑一批：取摘要 → 抽四元组 → 落盘。返回 (成功篇数, 用量快照)。

    `models` 给一串模型名时，**某个模型的免费额度用完就换下一个**
    （百炼按模型各算 100 万，2328 篇摘要一个模型装不下）。
    换模型这件事会打进日志，且每条记录都记着自己是哪个模型抽的 ——
    不然日后发现某一段质量不对，查不出是谁的手笔。
    """
    queue = list(models or [_model()])
    cur = queue.pop(0)
    todo = pending(band, limit, seeds_only)
    if not todo:
        log('这条窄带的摘要都抽过了')
        return 0, {}
    log('待抽 %d 篇（按被引数从高到低）' % len(todo))
    before = llm_client.usage_snapshot()
    t0 = time.time()
    done = failed = no_abs = 0
    for i in range(0, len(todo), BATCH_ABSTRACTS):
        chunk = todo[i:i + BATCH_ABSTRACTS]
        abs_map = _abstracts([w[0] for w in chunk])
        for wid, doi, title, venue, year in chunk:
            text = abs_map.get(wid)
            if not text:
                no_abs += 1
                continue
            while True:
                try:
                    if one(wid, title, text, doi, venue, year, model=cur):
                        done += 1
                    else:
                        failed += 1
                    break
                except Exception as e:
                    if is_quota_exhausted(e) and queue:
                        nxt = queue.pop(0)
                        log('  [额度用完] %s 的免费额度到头了，换 %s 接着跑' % (cur, nxt))
                        cur = nxt
                        continue          # 同一篇用新模型重来，不丢
                    if is_quota_exhausted(e):
                        log('  [停] %s 也没额度了，且没有备选模型。已抽 %d 篇。' % (cur, done))
                        raise SystemExit(0)
                    failed += 1
                    log('  [失败] %s %s' % (wid, str(e)[:80]))
                    break
            if done and done % 10 == 0:
                log('  已抽 %d 篇（用时 %ds）' % (done, round(time.time() - t0)))
    after = llm_client.usage_snapshot()
    used = {'calls': after['calls'] - before['calls'],
            'in': after['prompt'] - before['prompt'],
            'out': after['completion'] - before['completion'],
            'model': after.get('model'), 'secs': round(time.time() - t0)}
    log('完成：%d 篇成功、%d 篇没有摘要、%d 篇失败；用时 %ds' % (done, no_abs, failed, used['secs']))
    log('用量：%d 次调用，输入 %d tok、输出 %d tok（模型 %s）'
        % (used['calls'], used['in'], used['out'], used['model']))
    if done:
        log('平均一篇：输入 %d tok、输出 %d tok、%.1fs'
            % (used['in'] / done, used['out'] / done, used['secs'] / done))
    return done, used


def main():
    """命令行入口。`--list` 只数数不花钱；其余是**花钱的批量作业**。"""
    band = opt('--band') or 'impact'
    seeds_only = not flag('--all')
    if flag('--list'):
        todo = pending(band, seeds_only=seeds_only)
        print('窄带 %s：还没抽摘要的有 %d 篇（%s）；已抽 %d 篇'
              % (band, len(todo), '只算种子层' if seeds_only else '含引用层',
                 len(paths.all_work_ids())))
        return
    lim = opt('--limit')
    role.require_prod('方向层摘要抽取（每篇一次云端小模型调用，是花钱的批量作业）',
                      force=flag('--force'))
    ms = opt('--models')
    run(band, int(lim) if lim else None, seeds_only=seeds_only,
        models=[m.strip() for m in ms.split(',') if m.strip()] if ms else None)


if __name__ == '__main__':
    main()
