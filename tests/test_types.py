# -*- coding: utf-8 -*-
"""类型检查棘轮：任何文件的 pyright 错误数不许超过基线。

为什么、怎么记基线、它发现不了什么 → 见 `host/doctor/typecheck.py` 的文档字符串。
这里只是把它接进「离线测试必须全绿」这道闸。

没装 pyright 的机器上跳过 —— 但**跳过是显式的、带原因的**，不是静悄悄不跑
（踩坑 #83 那一类）。A 机（唯一改代码的地方）必须装：pip install pyright
"""
import pytest

from host.doctor import typecheck


def test_类型错误不许比基线多():
    if not typecheck.is_available():
        pytest.skip('本机没装 pyright（pip install pyright）；改代码的机器必须装')
    counts, diags = typecheck.run()
    worse, _better = typecheck.compare(counts, typecheck.load_baseline())
    lines = []
    for f, was, now in worse:
        lines.append(f'{f}: 基线 {was} 条 → 现在 {now} 条')
        lines += [f'    {ln}: [{rule}] {msg}' for rel, ln, rule, msg in diags if rel == f]
    assert not worse, ('这些文件新引入了类型错误（修掉，或确认是误报后加 `# type: ignore`）：\n  '
                       + '\n  '.join(lines))
