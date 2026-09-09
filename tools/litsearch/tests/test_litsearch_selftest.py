# -*- coding: utf-8 -*-
"""把 litsearch 的离线自测接进 pytest —— 自测跑不过，改动就不许合。

自测本身是纯离线的（不联网、不碰用户数据），所以在 CI / 编程端 / 主力机上
行为一致，可以无条件跑。
"""
import subprocess
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))


def test_litsearch自测全过():
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'litsearch', 'selftest.py')],
                       capture_output=True, text=True, encoding='utf-8', errors='replace',
                       cwd=ROOT)
    assert r.returncode == 0, 'litsearch 自测没全过：\n' + (r.stdout or '') + (r.stderr or '')
