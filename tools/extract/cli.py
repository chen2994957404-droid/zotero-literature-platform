# -*- coding: utf-8 -*-
"""结构化抽取的命令行入口（只解析参数，逻辑在 tools/extract 与 batch.py）。

用法:
    python -m tools.extract                 抽取所有未处理的（增量，**全库作业**）
    python -m tools.extract <KEY>           只抽某一篇
    python -m tools.extract --rebuild       重抽全部（覆盖前自动备份）
    python -m tools.extract --parse         缺 full.md 的先 MineRU 解析
    python -m tools.extract --coarse        粗层全库（本地模型，零成本）
    python -m tools.extract --si-pending    只重抽「有 SI 却没读 SI」的
    python -m tools.extract --si-pending --list    只列清单，不花钱
    python -m tools.extract --local         改用本地 Ollama（零花费）
    python -m tools.extract --upgrade-local 把本地模型抽的改用云端重抽

⚠ 不带 key 就是**全库作业**：云端每篇都花钱。role.require_prod 会拦在编程端。

同一工具下另有两个独立入口，不走这里：
    python -m tools.extract.wizard          重抽向导（给用户双击的）
    python -m tools.extract.compare_models  比一比两个模型
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import role
from shared.kernel.cli import flag, opt, pos, wants_help
from shared.kernel.config import drop_stale_env
from shared.domain import schema
from shared.kernel import paths
from tools import extract
from tools.extract.batch import backup, coarse_all, extract_many



def main():
    """用法见模块文档字符串（`python -m tools.extract --help`）。"""
    if wants_help():
        print(__doc__)
        return 0
    only_key = pos(0)
    rebuild = flag('--rebuild')
    si_pending = flag('--si-pending')
    upgrade_local = flag('--upgrade-local')

    if flag('--local'):
        # 抽取走本地 Ollama。**只在这里设一次**，tools/extract 每次调用都读它。
        os.environ['EXTRACT_PROVIDER'] = 'ollama'
    drop_stale_env(log=print)      # 作废的旧密钥可能还躺在本进程的环境里（踩坑 #73）

    if flag('--coarse'):
        # 全库作业只允许在运行端跑（见 docs/howto/两台机器的分工.md）
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
        # 全库作业：花钱且量大，只允许在运行端跑（见 docs/howto/两台机器的分工.md）
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
