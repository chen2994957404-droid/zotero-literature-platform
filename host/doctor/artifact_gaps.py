# -*- coding: utf-8 -*-
"""查库里的半成品：哪些文献缺核心产物，以及它们停在了哪一步。

**为什么需要它**：主力机体检报「缺核心产物的文献：4 篇」，但只给了 key，
看不出是「解析失败」还是「精读做了一半」。而这两种情况的处理办法完全不同。

半成品最可能的来源，是精读中途 watcher 被看门狗误杀（踩坑见 shared/kernel/heartbeat.py）。
那个 bug 已修，但**之前留下的半成品不会自己消失**，得找出来重做。

本脚本**只读**，不删不改任何东西 —— 要重做哪几篇由你决定。

用法：
    python host/doctor/artifact_gaps.py           # 列出所有半成品
    python host/doctor/artifact_gaps.py KEY1 KEY2  # 只看指定几篇
"""
import os
import sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
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
    d = paths.paper_dir(key)
    for dirpath, _dirs, files in os.walk(d):
        for f in files:
            try:
                size += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return missing, present, size / 1024 / 1024


def diagnose(missing, present):
    """从「缺了什么」推断它停在哪一步，并给出建议。

    ⚠ **建议必须区分「要花钱」和「不花钱」**。2026-08-27 我第一版把「只缺
    meta.json」也判成「重新打待处理标签」—— 那会让 4 篇已经精读完的文献
    整篇重跑一遍 MineRU + DeepSeek，白花钱补一个从 Zotero 读一下就有的字段。
    """
    if not missing:
        return '完整', ''
    # 精读全做完了，只是元数据没落盘 —— 最省事的一类，别当成半成品重跑
    if missing == ['meta'] and 'summary' in present:
        return ('精读已完成，只差元数据',
                '跑 `python 库房维护/backfill_meta.py` 从 Zotero 补一下即可 —— '
                '**不调大模型、不花钱**。千万别重新打「待处理」标签重跑整篇')
    if 'fulltext' not in present:
        return ('解析就没成功', '重新打「待处理」标签即可，整篇会从头做一遍')
    if 'summary' in missing:
        return ('正文解析好了，精读没做完',
                '重新打「待处理」标签；解析结果还在，不会重复花 MineRU 的钱')
    if 'meta' in missing:
        return ('缺元数据', '跑 `python 库房维护/backfill_meta.py` 补，不花钱')
    return ('产物不齐', '把这一行发给 Claude 判断，先别急着重跑（重跑要花钱）')


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

    print('注意：本脚本只看不改。要重做的话，去 Zotero 给这几篇重新打「待处理」标签，')
    print('精读监听会自动接手（它现在不会再被看门狗中途杀掉了）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
