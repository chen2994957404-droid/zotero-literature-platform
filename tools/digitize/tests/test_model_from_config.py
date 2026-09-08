# -*- coding: utf-8 -*-
"""看图用哪个模型，必须**来自配置**，不许躺在代码里（踩坑 #139）。

2026-09-07：写死在 adapters 里的 `deepseek-vl2` 被服务商下线，
于是 292 张图一张都抠不出来，症状只是 HTTP 400 ——
而不懂编程的用户在控制面板上**根本找不到这一项**可以改。
这条测试钉住的就是「模型名是配置项」这件事。
"""
from shared.kernel import config
from tools import digitize


def test_没指定模型时用配置里的那个(monkeypatch):
    seen = {}

    def _fake(system, user, b64, provider=None, model=None, **kw):
        seen['model'] = model
        return '{"chart_type": "line", "series": []}'

    monkeypatch.setattr(digitize, 'chat_vision', _fake)
    digitize.digitize('AAAA')
    assert seen['model'] == config.get_model('DIGITIZE_MODEL')
    assert seen['model'], '配置里必须有一个真实的默认值，不能是空'


def test_调用方指定的模型优先(monkeypatch):
    """比一比两个模型时要能临时换 —— 配置是默认值，不是枷锁。"""
    seen = {}
    monkeypatch.setattr(digitize, 'chat_vision',
                        lambda s, u, b, provider=None, model=None, **kw:
                        (seen.update(model=model), '{"series": []}')[1])
    digitize.digitize('AAAA', model='qwen3-vl-plus')
    assert seen['model'] == 'qwen3-vl-plus'


def test_这一项在控制面板上看得见():
    """用户换模型的唯一入口是面板，面板列的就是 MODEL_SETTINGS。"""
    assert 'DIGITIZE_MODEL' in config.MODEL_SETTINGS
    label, default = config.MODEL_SETTINGS['DIGITIZE_MODEL']
    assert label and default
