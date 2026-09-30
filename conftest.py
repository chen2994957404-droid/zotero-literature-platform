# -*- coding: utf-8 -*-
"""全项目 pytest 公共夹具。

**心跳信号写进临时目录**（2026-09-16）：取件 / 落地 / 金标 / 回填都会写 `heartbeat.progress()`，
跑测试时这些会落到真实的 `data/logs/`，面板就会显示「金标取件 在跑」—— 测试不该留下运行痕迹。
**日志也写进临时目录**（2026-09-30）：日志器在创建时就把文件开在 `paths.LOGS` 下，
而部署时主力机的体检会跑一遍测试 —— 于是真日志里混满了测试的假记录（`10.1/b 没拿到`、
看门狗日志里的「[b] 端口 2 没在监听」），排查时分不清哪条是真的。
这里在**任何测试模块被导入之前**把日志目录换掉（根 conftest 最先加载），所有日志器都开在临时目录里。
"""
import os
import tempfile

import pytest

from shared.kernel import paths as _paths

_paths.LOGS = os.path.join(tempfile.gettempdir(), 'litplatform-test-logs')


@pytest.fixture(autouse=True)
def _heartbeat_to_tmp(tmp_path, monkeypatch):
    from shared.kernel import heartbeat
    monkeypatch.setattr(heartbeat.paths, 'runtime', lambda name, **kw: str(tmp_path / 'rt' / name))
    yield
