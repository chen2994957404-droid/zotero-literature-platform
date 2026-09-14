# -*- coding: utf-8 -*-
"""python -m host.ingest [--limit N] [--不向量化] —— 把证据库里积压的免费三步做完。"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import role
from shared.kernel.cli import flag, opt
from host import ingest


def main():
    # 会花 MineRU 额度、写 data/raw —— 编程端默认拦住（测试角色放行）
    role.require_prod('落地流水线：解析 + 骨架 + 向量化（花 MineRU 额度）', force=flag('--force'))
    c = ingest.run_backlog(limit=opt('--limit'), with_vectors=not flag('--不向量化'))
    print('')
    print(f'做完：解析 {c["parsed"]} 篇 · SI {c["si_parsed"]} 篇 · 骨架 {c["outlined"]} 篇 · '
          f'向量化 {c["vectorized"]} 篇 · 失败 {c["failed"]} 篇')
    bad = ingest.failures()
    if bad:
        print('等重试的（一天后再试）：')
        for pid, step, err in bad:
            print(f'  {pid}  {step}  {err}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
