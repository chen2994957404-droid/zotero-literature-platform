# -*- coding: utf-8 -*-
"""journalwatch 的离线测试：一层壳，判据写在 selftest.py（体检与 pytest 同时受益）。"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SELFTEST = os.path.join(os.path.dirname(HERE), 'selftest.py')


def test_journalwatch自测全过():
    r = subprocess.run([sys.executable, SELFTEST], capture_output=True,
                       text=True, encoding='utf-8', errors='replace', timeout=120)
    assert r.returncode == 0, (
        'journalwatch/selftest.py 没过：\n' + (r.stdout or '') + (r.stderr or ''))
