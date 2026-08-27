# -*- coding: utf-8 -*-
"""结构化抽取的命令行入口 —— **逻辑已搬进 `pipelines/extract` 与 `domain/schema`**。

用法:
  python extract_structured.py              # 抽取所有未处理的文献（增量）
  python extract_structured.py --rebuild    # 重抽全部
  python extract_structured.py <KEY>        # 只抽某一篇

搬家原因（阶段 3 下半，2026-08-27）：这个脚本此前既是程序又是库 ——
watcher 用 subprocess 拉它，另外两个脚本 `from extract_structured import ...`。
现在字段 schema 在 `domain/schema`（纯逻辑，十年不变），
读写与编排在 `pipelines/extract`（需求一变就变），本文件只剩参数解析。

**要改抽什么字段，去改 `domain/schema/__init__.py`，并把 `SCHEMA_VER` +1。**
"""
import sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from core import paths, role
from core.cli import flag, pos
from domain import schema
from pipelines import extract


def main():
    only_key = pos(0)
    rebuild = flag('--rebuild')
    if not only_key:
        # 全库作业：花钱且量大，只允许在运行端跑（见 docs/两台机器的分工.md）
        role.require_prod('全库结构化抽取（每篇都调用付费 API）', force=flag('--force'))

    keys = [only_key] if only_key else paths.all_keys()
    print(f'结构化抽取 {len(keys)} 篇（schema v{schema.SCHEMA_VER}'
          f'{"，强制重抽" if rebuild else "，已抽过的跳过"}）\n')
    done = 0
    for key in keys:
        rec = extract.run(key, force=rebuild or bool(only_key))
        if rec:
            done += 1
    extract.write_compare_table()
    print(f'\n完成：本次 {done} 篇，库内共 {len(extract.all_records())} 条结构化记录')
    print(f'对比表：{paths.compare()}')


if __name__ == '__main__':
    main()
