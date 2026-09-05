# -*- coding: utf-8 -*-
"""getpdf 的离线测试：把 selftest 当子进程跑一遍，并单验几个不变量。

**不联网、不碰浏览器。** 这个工具真正的行为在别人家的浏览器里，
本机能验的只有「不联网也必须成立」的那部分。
"""
import subprocess
import sys

from shared.adapters import pdf_fetch
from tools import getpdf


def test_selftest_passes():
    """selftest 全绿 —— 它是这块的第一道闸。"""
    r = subprocess.run([sys.executable, 'tools/getpdf/selftest.py'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def test_defaults_stay_conservative():
    """默认值是防出版商风控的唯一一道闸 —— 有人想调快时应该先看见这个红。

    风控封的是整个机构的 IP，代价由全校承担，所以这条不是风格问题。
    """
    assert getpdf.GAP >= 10
    assert getpdf.LIMIT <= 50


def test_doi_filter_drops_junk():
    """非 DOI 的输入不许流到取全文那一步（免得白敲出版商一次）。"""
    assert pdf_fetch.is_doi('10.1016/j.cej.2025.164092')
    assert not pdf_fetch.is_doi('https://doi.org/10.1016/x')
    assert not pdf_fetch.is_doi('随便一句话')


def test_reasons_all_have_human_words():
    """每种 reason 都得有句人话 —— 用户不懂编程，看的是这句。"""
    for k, v in pdf_fetch.REASONS.items():
        assert v and len(v) >= 3, k
