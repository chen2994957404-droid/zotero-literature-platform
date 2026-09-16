# -*- coding: utf-8 -*-
"""全项目 pytest 公共夹具。

**心跳信号写进临时目录**（2026-09-16）：取件 / 落地 / 金标 / 回填都会写 `heartbeat.progress()`，
跑测试时这些会落到真实的 `data/logs/`，面板就会显示「金标取件 在跑」—— 测试不该留下运行痕迹。
"""
import pytest


@pytest.fixture(autouse=True)
def _heartbeat_to_tmp(tmp_path, monkeypatch):
    from shared.kernel import heartbeat
    monkeypatch.setattr(heartbeat.paths, 'runtime', lambda name, **kw: str(tmp_path / 'rt' / name))
    yield
