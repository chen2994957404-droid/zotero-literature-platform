# -*- coding: utf-8 -*-
"""bibliometrics 的离线测试（R7 窗从 `shared/domain/` 搬进本工具后的接续）。

**为什么要有这一条**：它原来是 `shared/domain/bibliometrics/`，
体检靠 `paths.block_dirs()` 挨个跑各环的 `selftest.py`，所以一直被跑到。
R7 窗按第三节硬规则 1（下沉规则：只有 1 个工具用的不许住 shared/）
把它搬进 `tools/direction/` 之后，它就不再是「环里的一块」，
**体检从此不会再跑它** —— 不补这一条，一整份 IDF/Louvain/趋势的判据会静悄悄失去覆盖。

这正是搬家最容易出的事故（同踩坑 #83：改了位置，守卫静默空转）。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SELFTEST = os.path.join(os.path.dirname(HERE), 'bibliometrics', 'selftest.py')


def test_文献计量自测全过():
    r = subprocess.run([sys.executable, SELFTEST], capture_output=True,
                       text=True, encoding='utf-8', errors='replace', timeout=120)
    assert r.returncode == 0, (
        'bibliometrics/selftest.py 没过：\n' + (r.stdout or '') + (r.stderr or ''))
