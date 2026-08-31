# -*- coding: utf-8 -*-
"""ask 的离线测试。

**为什么是一层壳**：这个工具的离线判据本来就写在 `ask/selftest.py` 里 ——
体检（`host/doctor/health_check.py`）会挨个跑它们，那是给用户看的那条路。
这里把同一份判据接进 pytest，让 `python -m pytest -q` 一条命令也能拦住人，
不必先想起还有个体检要跑。

**新增判据请写进 `selftest.py`**（那样体检和 pytest 同时受益），
只有需要 fixture / 参数化 / tmp_path 的才在本目录另开文件。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SELFTEST = os.path.join(os.path.dirname(HERE), 'selftest.py')


def test_ask自测全过():
    r = subprocess.run([sys.executable, SELFTEST], capture_output=True,
                       text=True, encoding='utf-8', errors='replace', timeout=120)
    assert r.returncode == 0, (
        'ask/selftest.py 没过：\n' + (r.stdout or '') + (r.stderr or ''))
