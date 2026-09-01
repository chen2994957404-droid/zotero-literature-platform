# -*- coding: utf-8 -*-
"""`digitize_paper()` 的契约测试（不调模型、不碰真实数据）。

**这个入口为什么存在**：此前只有「给我一张图片文件」，而用户手里从来不是
图片文件，是一篇 Zotero 文献。中间那步「从解析产物里裁 Figure」写在文档里
让调用方自己做 —— 等于把最容易做错的一步（踩坑 #7 的智慧都在 figure_crop 里）
推给了别人。顺带它也解掉了架构守卫的一条豁免：`shared/domain/figure_crop`
从此有两个真实使用者（deepread 与 digitize），符合下沉规则。
"""
import pytest

from tools import digitize


def test_没解析过的文献返回空字典而不是抛异常():
    """`digitize` 一族的契约是**不抛异常**，这个入口不能例外。

    对调用方来说，「这篇没有曲线图」和「这篇还没解析」是同一件事：
    这次没东西可做。让它抛 FileNotFoundError 会把这个区别硬塞给每个调用点。
    """
    assert digitize.digitize_paper('ZZZZ9999') == {}


def test_怪key也只是空字典():
    """key 来自 Zotero 的一批条目，混进一个怪的不该让整批崩掉。"""
    assert digitize.digitize_paper('不是key') == {}


def test_only参数只做指定的图(monkeypatch):
    """整篇 = 每张图各调一次云端视觉模型，**是要花钱的**。
    `only` 不生效意味着用户想读 1 张、实际付了 10 张的钱。
    """
    fake = [{'b64': 'a', 'num': 1, 'caption': '图1'},
            {'b64': 'b', 'num': 2, 'caption': '图2'},
            {'b64': 'c', 'num': 3, 'caption': '图3'}]
    monkeypatch.setattr('shared.domain.figure_crop.crop_figures', lambda d: fake)
    monkeypatch.setattr('shared.kernel.paths.parsed_dir', lambda k, create=False: '.')
    called = []

    def _fake_digitize(b64, **kw):
        called.append(b64)
        return {'chart_type': 'line', 'series': []}

    monkeypatch.setattr(digitize, 'digitize', _fake_digitize)

    out = digitize.digitize_paper('AAAA1111', only=[2, 3])
    assert sorted(out) == [2, 3], f'只要 2、3 张，实际 {sorted(out)}'
    assert called == ['b', 'c'], '多调了模型 = 多花了钱'
    assert out[2]['caption'] == '图2', '图注要带上，否则没法判断读的是哪张'
