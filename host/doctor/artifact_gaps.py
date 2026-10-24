# -*- coding: utf-8 -*-
"""查库里的半成品：哪些文献缺核心产物，以及它们停在了哪一步。

**为什么需要它**：主力机体检报「缺核心产物的文献：4 篇」，但只给了 key，
看不出是「没解析」还是「缺元数据」。而这两种情况的处理办法不同。

本脚本**只读**，不删不改任何东西 —— 要重做哪几篇由你决定。

用法：
    python host/doctor/artifact_gaps.py           # 列出所有半成品
    python host/doctor/artifact_gaps.py KEY1 KEY2  # 只看指定几篇
"""
import os
import sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.kernel import paths
from shared.kernel.cli import positionals

def inspect(key):
    """看一篇文献的产物齐不齐。返回 (缺的, 有的, 目录大小MB)。

    「缺哪些」是数据契约的问题，交给 `shared.kernel.paths.missing_artifacts` 回答 ——
    产物清单只该有一份。
    """
    missing, present = paths.missing_artifacts(key)
    size = 0
    # R6 起一篇文献占**两个**目录：raw（解析产物，占绝大部分体积）+ curated
    # （目录卡、骨架、整图）。只走一个的话报出来的「占多大」会小一个数量级。
    for d in (paths.paper_raw_dir(key), paths.paper_dir(key)):
        for dirpath, _dirs, files in os.walk(d):
            for f in files:
                try:
                    size += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
    return missing, present, size / 1024 / 1024


def diagnose(missing, present):
    """从「缺了什么」推断它停在哪一步，并给出建议。

    ⚠ **建议必须区分「要花钱」和「不花钱」**。2026-08-27 第一版把「只缺
    meta.json」也判成「整篇重跑」—— 那会白花一遍解析额度，去补一个登记一下就有的字段。
    """
    if not missing:
        return '完整', ''
    if 'fulltext' not in present or 'layout' in missing:
        return ('还没解析（或解析不完整）',
                '跑一次落地流水线 `python -m host.ingest` 补上 —— 只用 MineRU 额度，不花大模型的钱')
    if 'meta' in missing:
        return ('缺元数据', '把这一行发给 Claude 按 DOI 补目录卡，不花钱')
    return ('产物不齐', '把这一行发给 Claude 判断')


def main():
    keys = [k.upper() for k in positionals()] or paths.all_keys()
    if not keys:
        print('library 里一篇文献都没有 —— 这台机器多半是编程端。')
        return 0

    bad = []
    for key in keys:
        try:
            missing, present, size = inspect(key)
        except Exception as e:
            print(f'{key}: 查不了（{type(e).__name__}: {e}）')
            continue
        if missing:
            bad.append((key, missing, present, size))

    print(f'扫了 {len(keys)} 篇，其中 {len(bad)} 篇产物不全。')
    if not bad:
        print('全部符合数据契约。')
        return 0

    print('')
    for key, missing, present, size in bad:
        stage, advice = diagnose(missing, present)
        print(f'── {key}  （{size:.1f} MB）')
        print(f'   停在：{stage}')
        print(f'   有：{"、".join(present) or "（什么都没有）"}')
        print(f'   缺：{"、".join(missing)}')
        if advice:
            print(f'   建议：{advice}')
        print('')

    print('注意：本脚本只看不改。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
