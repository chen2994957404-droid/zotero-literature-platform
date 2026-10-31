# -*- coding: utf-8 -*-
"""extract_dois：人随手贴进来的一段文字 → DOI（文献库应用「导入」用）。离线。"""
from tools.getpdf import extract_dois


def test_一行一个与各种前缀():
    text = '10.1021/acs.macromol.5b01234\nhttps://doi.org/10.1002/ADFM.202411821\ndoi:10.1016/j.cej.2025.164092'
    assert extract_dois(text) == ['10.1021/acs.macromol.5b01234', '10.1002/adfm.202411821',
                                  '10.1016/j.cej.2025.164092']


def test_参考文献里的句号括号不算():
    text = ('[1] Zhang, S. Adv. Mater. 2020, 32, 1904. (https://doi.org/10.1002/adma.201904752).\n'
            '[2] 见 10.1039/c9py01234a，另见 10.1021/jacs.0c01234。')
    assert extract_dois(text) == ['10.1002/adma.201904752', '10.1039/c9py01234a', '10.1021/jacs.0c01234']


def test_DOI里本来就有的括号要留着():
    assert extract_dois('10.1016/S0032-3861(02)00123-4.') == ['10.1016/s0032-3861(02)00123-4']


def test_出版商网址与去重():
    text = ('https://onlinelibrary.wiley.com/doi/10.1002/adfm.202411821/full\n'
            'https://pubs.acs.org/doi/pdf/10.1021/acs.macromol.5b01234\n10.1002/adfm.202411821')
    assert extract_dois(text) == ['10.1002/adfm.202411821', '10.1021/acs.macromol.5b01234']


def test_没有DOI():
    assert extract_dois('') == [] and extract_dois('聚硼硅氧烷 自愈合') == []
