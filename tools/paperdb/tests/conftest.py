# -*- coding: utf-8 -*-
"""paperdb 测试的公共隔离：**把这个库读的每一个源都指到临时目录**。

为什么单独立一份（2026-09-07，同一个疏忽栽了三次）：
`paperdb` 的源在一天之内从「一个目录」长到了四个 ——
`structured/`（细节层）、`abstracts/`（方向层）、`curated/<key>/curves.json`（曲线）、
`serving/journals.json`（期刊分级）。每加一个源，三份测试文件里的隔离就漏一处；
**而漏了在编程端是绿的**（那台机器几乎没有数据），一到主力机才红。

所以隔离不该抄三遍。以后再加源，只改这里 —— 忘了改，主力机上会立刻红，
而不是安静地把用户的真实数据算进金标评测里。
"""
import pytest

from shared.kernel import paths
from tools import paperdb

# paperdb 会去读的每一个 paths 属性。加源就往这里加。
SOURCES = ('STRUCTURED', 'ABSTRACTS', 'CURATED', 'SERVING')


@pytest.fixture
def isolate(tmp_path, monkeypatch):
    """把 paperdb 的全部源与库文件指到 tmp_path，返回 `structured/` 目录。"""
    for name in SOURCES:
        d = tmp_path / name.lower()
        d.mkdir(exist_ok=True)
        monkeypatch.setattr(paths, name, str(d))
    monkeypatch.setattr(paperdb, 'db_path', lambda: str(tmp_path / 'papers.db'))
    paperdb.close()
    yield tmp_path / 'structured'
    paperdb.close()
