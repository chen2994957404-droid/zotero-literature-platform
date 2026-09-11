# -*- coding: utf-8 -*-
"""看图用哪个模型，必须**来自配置**，不许躺在代码里（踩坑 #139）。

2026-09-07：写死在 adapters 里的 `deepseek-vl2` 被服务商下线，
于是 292 张图一张都抠不出来，症状只是 HTTP 400 ——
而不懂编程的用户在控制面板上**根本找不到这一项**可以改。
这条测试钉住的就是「模型名是配置项」这件事。

2026-09-11 起配置在**路由表**里（`shared.kernel.config.routing`）：
调用方只说 `purpose='DIGITIZE'`，走哪条通道、用哪个模型由表决定。
意图不变（模型来自配置），机制变了（从 get_model 变成路由表），测试跟着改。
"""
from shared.kernel import config
from shared.kernel.config import routing
from tools import digitize


def test_没指定模型时只报用途_由路由表定模型(monkeypatch):
    """digitize 自己**不该**去查模型名 —— 那是路由表的事。它只说「我是图表数字化」。"""
    seen = {}

    def _fake(system, user, b64, provider=None, model=None, purpose=None, **kw):
        seen.update(model=model, purpose=purpose)
        return '{"chart_type": "line", "series": []}'

    monkeypatch.setattr(digitize, 'chat_vision', _fake)
    digitize.digitize('AAAA')
    assert seen['purpose'] == 'DIGITIZE'
    assert seen['model'] is None, '没指定就该留给路由表，不该在这里塞一个默认值'


def test_路由表给图表数字化配的模型来自配置_不是写死的():
    """把 #139 的教训钉在路由表上：DIGITIZE 的模型必须能从 MODEL_SETTINGS/面板改。"""
    p = routing.purposes()['DIGITIZE']
    assert p['model'] == config.get_model('DIGITIZE_MODEL')
    assert p['model'], '配置里必须有一个真实的默认值，不能是空'
    assert 'vision' in p['needs'], '这个用途必须声明要看图，通道不支持时体检才报得出来'


def test_调用方指定的模型优先(monkeypatch):
    """比一比两个模型时要能临时换 —— 配置是默认值，不是枷锁。"""
    seen = {}
    monkeypatch.setattr(digitize, 'chat_vision',
                        lambda s, u, b, provider=None, model=None, **kw:
                        (seen.update(model=model), '{"series": []}')[1])
    digitize.digitize('AAAA', model='qwen3-vl-plus')
    assert seen['model'] == 'qwen3-vl-plus'


def test_这一项在控制面板上看得见():
    """用户换模型的唯一入口是面板，面板列的就是 MODEL_SETTINGS（路由表以它为默认）。"""
    assert 'DIGITIZE_MODEL' in config.MODEL_SETTINGS
    label, default = config.MODEL_SETTINGS['DIGITIZE_MODEL']
    assert label and default
    assert 'DIGITIZE' in routing.PURPOSES
