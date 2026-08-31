# -*- coding: utf-8 -*-
"""精读的命令行入口（只解析参数，逻辑在 tools/deepread 与 batch.py）。

用法:
    python -m tools.deepread KEY1 KEY2          批量正文精读
    python -m tools.deepread --file keys.txt    从文件读 key（每行一个）
    python -m tools.deepread --force ...        强制重跑（旧版自动备份 .bak）
    python -m tools.deepread --si KEY1 KEY2     批量补 SI 精读 + 合并 + 回写
    python -m tools.deepread --upload KEY1      批量回写 summary 附件 + 打标签
    python -m tools.deepread --refresh KEY1     只把新版铺进本地 storage
    python -m tools.deepread --rerun-pro        列出可用 pro 重跑的文献
    python -m tools.deepread --rerun-pro 3      用 pro 重跑第 3 篇

⚠ 除 --rerun-pro 列清单外，每一条都**花钱**（付费大模型 + MineRU 额度），
   并且会把结果写回 Zotero。只允许在主力机上跑（role.require_prod 会拦）。

常驻服务另有自己的入口，不走这里：
    python -m tools.deepread.watcher     盯着 Zotero 的「待处理」标签自动精读
    python -m tools.deepread.watchdog    看门狗（守着 watcher 别死）
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel.cli import flag, opt, positionals, wants_help
from tools.deepread.batch import (read_many, refresh_local_file, rerun_candidates,
                                  rerun_with_pro, si_many, upload_many)



def main():
    """用法见模块文档字符串（`python -m tools.deepread --help`）。"""
    if wants_help():
        print(__doc__)
        return 0
    force = flag('--force')
    fp = opt('--file')
    keys = ([l.strip() for l in open(fp, encoding='utf-8') if l.strip()]
            if fp else positionals())

    if flag('--rerun-pro'):
        rows = rerun_candidates()
        idx_raw = opt('--rerun-pro') or (keys[0] if keys else '')
        if not idx_raw:
            print('=== 可用 pro 重跑的已解析文献 ===\n')
            for i, (_key, title) in enumerate(rows, 1):
                print(f'  [{i}] {title[:55]}')
            if not rows:
                print('  （没有已解析的文献 —— 先让 watcher 精读一篇）')
            print('\n用法：python -m tools.deepread --rerun-pro 2')
            return
        try:
            idx = int(idx_raw) - 1
        except ValueError:
            raise SystemExit('序号要是数字')
        if not 0 <= idx < len(rows):
            raise SystemExit('序号超范围')
        rerun_with_pro(rows[idx][0], rows[idx][1], force=force)
        return

    if flag('--refresh'):
        for key in keys:
            good, msg = refresh_local_file(key)
            print(f'  {key}: {"OK " if good else "跳过 "}{msg}')
        return
    if not keys:
        print(__doc__)
        raise SystemExit(2)
    if flag('--upload'):
        upload_many(keys, force=force)
    elif flag('--si'):
        si_many(keys, force=force)
    else:
        read_many(keys, force=force)


if __name__ == '__main__':
    main()
