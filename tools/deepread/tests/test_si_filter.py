# -*- coding: utf-8 -*-
"""si_filter 的离线测试（R7 窗从 `shared/domain/` 搬进本工具后的接续）。

理由同 `tools/direction/tests/test_bibliometrics.py`：它原来住在 `shared/domain/`，
体检按环枚举、挨个跑 `selftest.py`；搬进工具里之后就不再被枚举到，
不补这一条，「SI 里挑实验细节而不误杀」的那套判据会静悄悄失去覆盖。

**这份判据的重点是不误杀**（曾把 `Mw = 4200 g/mol`、¹¹B NMR 当成作者名单丢掉）——
误杀的表现是「精读结果里少了一段」，不会报错，所以只能靠测试拦。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SELFTEST = os.path.join(os.path.dirname(HERE), 'si_filter', 'selftest.py')


def test_si过滤自测全过():
    r = subprocess.run([sys.executable, SELFTEST], capture_output=True,
                       text=True, encoding='utf-8', errors='replace', timeout=120)
    assert r.returncode == 0, (
        'si_filter/selftest.py 没过：\n' + (r.stdout or '') + (r.stderr or ''))
