# -*- coding: utf-8 -*-
"""结构化抽取的命令行入口 —— **逻辑已搬进 `pipelines/extract` 与 `domain/schema`**。

用法:
  python extract_structured.py               # 抽取所有未处理的文献（增量）
  python extract_structured.py --rebuild     # 重抽全部
  python extract_structured.py <KEY>         # 只抽某一篇
  python extract_structured.py --si-pending  # 只重抽「有 SI 却没读 SI」的那些（花钱，见下）
  python extract_structured.py --si-pending --list   # 只列清单，不抽，不花钱
  python extract_structured.py --si-pending --local  # 同上，但用**本地 Ollama**，零花费
  python extract_structured.py --upgrade-local       # 把本地模型抽的那些改用云端重抽

**--local 是什么**：用主力机上的本地模型（Ollama）代替云端 DeepSeek。
料完全一样（MineRU 全文 + SI），只是模型小一档、慢一档（实测 ~137 秒/篇），
但**零花费、不限量**。这样抽出来的记录标成 `本地+SI` 档，绝不冒充 `精+SI` ——
以后云端密钥可用了，`--upgrade-local` 就是那份「值得花钱升级」的清单。

**覆盖前自动备份**：任何一次会覆盖已有结果的重抽，都会先把旧 JSON
整批复制到 `workflow_data/structured_bak_<时间戳>/`（踩坑 #16 的代价买来的教训）。

**--si-pending 是什么**：2026-08-28 之前的抽取根本没读补充材料，
而投料量/配比/温度时间几乎只写在 SI 里 —— 这正是 `synthesis_conditions`
有值率只有 36% 的原因。这些篇的 SI 早就解析好了（精读时解析的），
重抽只是每篇多花一次 DeepSeek 调用，不再解析 PDF。

搬家原因（阶段 3 下半，2026-08-27）：这个脚本此前既是程序又是库 ——
watcher 用 subprocess 拉它，另外两个脚本 `from extract_structured import ...`。
现在字段 schema 在 `domain/schema`（纯逻辑，十年不变），
读写与编排在 `pipelines/extract`（需求一变就变），本文件只剩参数解析。

**要改抽什么字段，去改 `domain/schema/__init__.py`，并把 `SCHEMA_VER` +1。**
"""
import os
import sys
import time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from core import paths, role
from core.cli import flag, pos
from core.config import drop_stale_env
from domain import schema
from pipelines import extract, paper_db


def _backup(keys):
    """覆盖前备份旧结果（实现在 pipelines/extract，向导与本 CLI 共用）。"""
    dest = extract.backup_records(keys)
    if dest:
        print(f'旧结果已备份 → {dest}')
    return dest


def main():
    only_key = pos(0)
    rebuild = flag('--rebuild')
    si_pending = flag('--si-pending')
    upgrade_local = flag('--upgrade-local')

    if flag('--local'):
        # 抽取走本地 Ollama。**只在这里设一次**，pipelines/extract 每次调用都读它。
        os.environ['EXTRACT_PROVIDER'] = 'ollama'
    drop_stale_env(log=print)      # 作废的旧密钥可能还躺在本进程的环境里（踩坑 #73）

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
        _backup(keys)                    # 覆盖前先备份（踩坑 #16）
    else:
        keys = [only_key] if only_key else paths.all_keys()
        if rebuild:
            _backup(keys)
    print(f'结构化抽取 {len(keys)} 篇（schema v{schema.SCHEMA_VER}，'
          f'{"本地 Ollama" if os.environ.get("EXTRACT_PROVIDER") == "ollama" else "云端 DeepSeek"}'
          f'{"，强制重抽" if rebuild else "，已抽过的跳过"}）\n', flush=True)
    done = 0
    t0 = time.time()
    for i, key in enumerate(keys, 1):
        # 进度要打在前面：本地模型一篇要两分多钟，没有进度就像卡死了
        print(f'[{i}/{len(keys)}] {key}  （已用时 {round(time.time() - t0)}s）', flush=True)
        rec = extract.run(key, force=rebuild or bool(only_key))
        if rec:
            done += 1
    extract.write_compare_table()
    paper_db.rebuild()          # 查询库是 JSON 的索引，抽完顺手重建（秒级、不花钱）
    print(f'\n完成：本次 {done} 篇，库内共 {len(extract.all_records())} 条结构化记录')
    print(f'对比表：{paths.compare()}')


if __name__ == '__main__':
    main()
