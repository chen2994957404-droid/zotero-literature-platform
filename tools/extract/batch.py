# -*- coding: utf-8 -*-
"""extract · 批量抽取：一批文献 → 结构化字段 → 并入横向对比表。

R2 窗（2026-08-30）把 `数据抽取/` 下三个各自为政的脚本并进这一个文件：

    extract_structured.py   精层批量（命令行入口，逻辑早已在 tools/extract）
    extract_batch.py        「缺 full.md 就先 MineRU 解析一次」的那条线
    extract_library.py      粗层全库（吃 Zotero 自带全文索引 + 本地 Ollama）

为什么并：三个脚本各自实现了一遍「读什么料 → 调哪个模型 → 写哪个盘 → 出哪张表」，
而它们只是同一件事的**料不同、模型不同**两个档次。合成一处之后，
「加一个字段」只需要改 `shared/domain/schema` 一个地方，三条线一起生效。

**对外契约**（`cli.py` / `mcp.py` 只许调这些，R4 窗接）：

| 函数 | 干什么 | 花钱 |
|---|---|---|
| `extract_many(keys, force)` | 精层批量抽取 + 出表 + 重建查询库 | 是（云端档） |
| `ensure_fullmd(key)`        | 没有 full.md 就补一次 MineRU 解析 | 否（免费额度） |
| `coarse_all(rebuild)`       | 粗层全库：Zotero 全文索引 + 本地模型 | 否 |
| `backup(keys)`              | 覆盖前整批备份旧结果（踩坑 #16） | 否 |

**要改抽什么字段，去改 `shared/domain/schema/__init__.py`，并把 `SCHEMA_VER` +1。**
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

from shared.adapters import zotero_client as zotero
from shared.adapters.pdf_parse import parse_pdf, PDFParseError
from shared.kernel import paths, role
from shared.kernel.cli import flag, pos
from shared.kernel.config import drop_stale_env
from shared.domain import schema
from tools import extract

MIN_FULLTEXT = 500      # Zotero 全文索引短于这个字数就当没有（多半是扫描件没 OCR）


def _rebuild_index(log=print):
    """抽完顺手重建查询库（秒级、不花钱）。

    ⚠ 这是 tools 调 tools（违反 REBUILD.md 第三节硬规则 2）。paperdb 是
    structured/*.json 的**索引**，抽完不刷新它，用户查到的就是旧数据。
    延迟 import + 失败不致命：抽取本身已经成了，索引没刷不该让它算失败。
    R7 窗定夺（要么把「刷索引」交给调用方，要么承认索引是抽取的一部分）。
    记在 docs/待办与需求.md。
    """
    try:
        from tools import paperdb
        paperdb.rebuild(log=log)
    except Exception as e:
        log(f'  [查询库重建失败，不影响抽取结果] {e}')


# ───────────────────────── 精层：MineRU 全文 + 云端模型 ─────────────────────────

def ensure_fullmd(key, log=print):
    """确保 `library/<key>/parsed/full.md` 存在：有则复用，无则调一次 MineRU。

    补的是 extract_structured 缺的一环 —— 缺 full.md 时它直接跳过。
    MineRU 有每日免费额度，解析零成本；解析结果与精读线共享，谁先跑谁生成。
    返回 full.md 路径或 None。
    """
    key = paths.check_key(key)
    md = paths.fulltext(key)
    if os.path.exists(md):
        log('  [复用] 已有 full.md')
        return md
    pdf = zotero.find_pdf(key)
    if not pdf:
        log('  [跳过] Zotero 里找不到正文 PDF')
        return None
    log(f'  [MineRU] 解析 {os.path.basename(pdf)} ...')
    try:
        parse_pdf(pdf, paths.parsed_dir(key, create=True))    # 已解析则复用
    except PDFParseError as e:
        log(f'  [MineRU失败] {e}')
        return None
    if not os.path.exists(md):
        log('  [MineRU失败] 未生成 full.md')
        return None
    log('  [MineRU完成] full.md 已生成')
    return md


def backup(keys, log=print):
    """覆盖前把这些篇的旧结果整批备份出去（踩坑 #16 的代价买来的）。"""
    dest = extract.backup_records(keys)
    if dest:
        log(f'旧结果已备份 → {dest}')
    return dest


def extract_many(keys, force=False, parse_missing=False, log=print):
    """精层批量抽取 → 出对比表 → 重建查询库。返回成功篇数。

    `parse_missing=True` 时，缺 full.md 的先补一次 MineRU 解析再抽
    （原 extract_batch.py 的行为）。
    """
    done = 0
    t0 = time.time()
    for i, key in enumerate(keys, 1):
        # 进度要打在前面：本地模型一篇要两分多钟，没有进度就像卡死了
        log(f'[{i}/{len(keys)}] {key}  （已用时 {round(time.time() - t0)}s）')
        if parse_missing and not ensure_fullmd(key, log=log):
            continue
        if extract.run(key, force=force, log=log):
            done += 1
    extract.write_compare_table()
    _rebuild_index(log=log)
    return done


# ───────────────────────── 粗层：Zotero 全文索引 + 本地模型 ─────────────────────────

def _library_articles():
    """Zotero 库里所有顶层文献条目（分页取完）。"""
    arts, start = [], 0
    while True:
        page = zotero.search_items(limit=100, start=start)
        if not page:
            break
        arts += page
        start += 100
        if len(page) < 100:
            break
    return [x for x in arts if x['data'].get('itemType') in
            ('journalArticle', 'conferencePaper', 'thesis', 'bookSection', 'book')]


def _already_done():
    """(已抽过的 key, 精层受保护的 key)。

    精层记录（source != 'coarse'）**即使 --rebuild 也不许被粗层盖掉**（踩坑 #16）。
    """
    done, protected = set(), set()
    if not os.path.isdir(paths.STRUCTURED):
        return done, protected
    for f in os.listdir(paths.STRUCTURED):
        if not f.endswith('.json'):
            continue
        k = f[:-5]
        done.add(k)
        try:
            rec = json.load(io.open(os.path.join(paths.STRUCTURED, f), encoding='utf-8'))
        except Exception:
            continue          # 单个结果文件损坏读不出 source，跳过保护判断
        if rec.get('source') != schema.SOURCE_COARSE:
            protected.add(k)
    return done, protected


def coarse_all(rebuild=False, log=print):
    """粗层全库抽取：吃 Zotero 自带的全文索引，用**本地模型**抽。

    与精层的关系（对称于向量化的两档）：
      精层 `extract_many`：吃 MineRU 高质量 full.md + SI，云端 DeepSeek，最准，供重点文献
      粗层 `coarse_all`（本函数）：吃 Zotero 全文索引，本地 qwen，够筛，供全库
    **已被精层抽过的 key 自动跳过**，绝不用低档结果覆盖高档结果。

    零 API 成本、不限量，专供「广撒网找方向」。返回 (新抽, 跳过, 无全文, 失败)。
    """
    os.environ['EXTRACT_PROVIDER'] = 'ollama'      # 粗层一律走本地模型
    done, protected = _already_done()
    arts = _library_articles()
    log(f'Zotero 顶层文献 {len(arts)} 篇，开始本地粗层结构化抽取'
        f'（模型 {extract._model()}）...\n')

    processed = skipped = nofull = failed = 0
    for x in arts:
        key, title = x['key'], x['data'].get('title', x['key'])
        if key in protected or (key in done and not rebuild):
            skipped += 1
            continue
        try:
            children = zotero.zget(f'/users/{zotero.USER_ID}/items/{key}/children')
        except Exception:
            continue          # 条目刚被删之类：跳过该篇，不中断全库流程
        att = next((c['key'] for c in children
                    if c['data'].get('contentType') == 'application/pdf'), None)
        if not att:
            nofull += 1
            continue
        txt = zotero.get_fulltext(att)
        if len(txt) < MIN_FULLTEXT:
            nofull += 1
            continue
        try:
            data = extract.llm_json(schema.SYS,
                                    schema.build_user_prompt(title, schema.hierarchical_body(txt)))
        except Exception as e:
            log(f'[抽取失败] {title[:40]}: {e}')
            failed += 1
            continue          # 单篇失败继续下一篇
        record = schema.make_record(key, title, x['data'].get('DOI', ''), data,
                                    source=schema.SOURCE_COARSE)
        os.makedirs(paths.STRUCTURED, exist_ok=True)
        json.dump(record, io.open(paths.structured(key), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=2)
        processed += 1
        log(f'[{processed}] {title[:45]}')

    extract.write_compare_table()      # 粗+精并入同一张对比表
    _rebuild_index(log=log)
    log(f'\n完成：新抽 {processed} 篇，已有跳过 {skipped}，'
        f'无全文 {nofull}，失败 {failed}')
    return processed, skipped, nofull, failed


# ───────────────────────── 命令行（R4 窗改由 cli.py 调用） ─────────────────────────

def main():
    """用法见 tools/extract/README.md（R4 窗补）。

      python -m tools.extract.batch                 抽取所有未处理的（增量）
      python -m tools.extract.batch --rebuild       重抽全部
      python -m tools.extract.batch <KEY>           只抽某一篇
      python -m tools.extract.batch --parse         缺 full.md 的先 MineRU 解析
      python -m tools.extract.batch --coarse        粗层全库（本地模型，零成本）
      python -m tools.extract.batch --si-pending    只重抽「有 SI 却没读 SI」的
      python -m tools.extract.batch --si-pending --list    只列清单，不花钱
      python -m tools.extract.batch --local         改用本地 Ollama（零花费）
      python -m tools.extract.batch --upgrade-local 把本地模型抽的改用云端重抽
    """
    only_key = pos(0)
    rebuild = flag('--rebuild')
    si_pending = flag('--si-pending')
    upgrade_local = flag('--upgrade-local')

    if flag('--local'):
        # 抽取走本地 Ollama。**只在这里设一次**，tools/extract 每次调用都读它。
        os.environ['EXTRACT_PROVIDER'] = 'ollama'
    drop_stale_env(log=print)      # 作废的旧密钥可能还躺在本进程的环境里（踩坑 #73）

    if flag('--coarse'):
        # 全库作业只允许在运行端跑（见 docs/两台机器的分工.md）
        role.require_prod('全库粗层结构化抽取（本地模型，不花钱但一样是全库作业）',
                          force=flag('--force'))
        coarse_all(rebuild=rebuild)
        print(f'对比表：{paths.compare()}')
        return

    pending = None
    if upgrade_local:
        pending = extract.local_keys()
        print(f'本地模型抽的（可升级成云端）：{len(pending)} 篇')
        for k in pending:
            print('  ' + k)
        if flag('--list') or not pending:
            return

    if si_pending:
        pending = extract.si_pending_keys()
        print(f'有 SI 但抽取时没读 SI 的文献：{len(pending)} 篇')
        for k in pending:
            print('  ' + k)
        if flag('--list') or not pending:
            return                       # 只看清单：不调模型、不花钱

    if not only_key:
        # 全库作业：花钱且量大，只允许在运行端跑（见 docs/两台机器的分工.md）
        role.require_prod('全库结构化抽取（云端每篇都花钱；--local 不花钱但一样是全库作业）',
                          force=flag('--force'))

    if si_pending or upgrade_local:
        keys, rebuild = pending, True    # 这些篇必须重抽（原记录料不够 / 档次低）
        backup(keys)                     # 覆盖前先备份（踩坑 #16）
    else:
        keys = [only_key] if only_key else paths.all_keys()
        if rebuild:
            backup(keys)

    print(f'结构化抽取 {len(keys)} 篇（schema v{schema.SCHEMA_VER}，'
          f'{"本地 Ollama" if os.environ.get("EXTRACT_PROVIDER") == "ollama" else "云端 DeepSeek"}'
          f'{"，强制重抽" if rebuild else "，已抽过的跳过"}）\n', flush=True)
    done = extract_many(keys, force=rebuild or bool(only_key),
                        parse_missing=flag('--parse'))
    print(f'\n完成：本次 {done} 篇，库内共 {len(extract.all_records())} 条结构化记录')
    print(f'对比表：{paths.compare()}')


if __name__ == '__main__':
    main()
