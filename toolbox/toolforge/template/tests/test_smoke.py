# -*- coding: utf-8 -*-
"""最起码的几条 —— 不连网、不碰真数据。

骨架自带这几条不是走过场：它们保证「这个仓库 clone 下来能跑」。
陌生人装完第一件事就是跑测试，红的话他直接就走了。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import {{NAME_MOD}} as tool  # noqa: E402


def test_没有配置也能import():
    """没有配置文件时也要能 import、能打印帮助 ——
    否则第一次用的人只看到一个 traceback。"""
    assert tool.load_conf('/nonexistent/nope.toml') == {}


def test_读不动的配置不当成空配置(tmp_path, capsys):
    """TOML 写坏了要**说出来**。静默当空配置，表现是「功能不好使」，会查错方向。"""
    bad = tmp_path / 'config.toml'
    bad.write_text('这不是 TOML [[[', encoding='utf-8')
    assert tool.load_conf(str(bad)) == {}
    assert '读不动' in capsys.readouterr().out


def test_取参():
    sys.argv = ['x', 'go', '--n', '3', '--flag']
    assert tool.positionals() == ['go']
    assert tool.opt('--n') == '3'
    assert tool.flag('--flag') and not tool.flag('--nope')


def test_子进程按UTF8解码():
    rc, out = tool.run([sys.executable, '-c', 'print("中文")'])
    assert rc == 0 and '中文' in out
