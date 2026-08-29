# -*- coding: utf-8 -*-
"""wechat_seed · 公众号推送 → 种子文献（外接口：把「别人的品味」变成一批 DOI）

## 为什么存在

方向地图需要一个**起点不烂**的种子集。用「高分子学人」公众号的推送做种子，
因为那是有品味的人替我们筛过的正样本 —— 实测它的期刊分布和这个领域参考文献的
期刊分布几乎同构（AM / AFM / Angew / CEJ / Science / JACS），说明它推的确实是主干。

## ⚠ 这一块被设计成**可抛弃**的，这是刻意的

- 微信接口随时会关：`wechat-article-exporter` 已于 2026-07-30 停止维护，
  因为它依赖的公众号后台搜索接口被官方关停。目前能用的下载工具只剩一条路。
- 下载工具的说明写着「仅供学习交流，24 小时内删除」。

所以本块**只从 md 里提取 DOI + 推送日期，正文提完即弃**：
方向库建在 OpenAlex 的 DOI 上，不建在微信上。明天工具挂了，
换掉这一个文件就行，地图照常运转。

## 实测数据（835 篇，2025-01-28 ~ 2026-08-28）

    文章 835 → 有 DOI 769（92.1%）→ OpenAlex 命中 754（占全部 90.3%）
    提不到 DOI 的那 66 篇基本不是论文推送（会议邀请、招聘、报到通知、营销文），
    **本来就该丢掉，而且是自动丢的**。

两个踩过的坑，都固化在代码里：

1. **DOI 里有非断行连字符 U+2011**，不归一化成 `-` 会白丢几篇。
2. 文件名形如 `期刊名+中文标题.md`，**不带日期**；日期在正文里
   （`_2026年8月1日 09:46_`），所以日期只能从正文抓。

对外接口：
    scan(dir)        → [{file, doi, pubdate, journal_hint}]，按文件名排序
    extract(text)    → (doi, pubdate)，单篇，纯函数便于测试

依赖：标准库。**本块不联网** —— 它读的是别人下载好的本地文件。
（放在 adapters 环是因为它是「外部世界的形状」的适配点，不是因为它联网。）
"""
import io
import os
import re

from core import errors


class SeedError(errors.BadInputError):
    """种子目录不对（不存在、里面没有 md）。调用方传错了，重试没意义。"""


# DOI：末尾要剔掉中文标点和右括号 —— 微信正文里 DOI 后面常紧跟「。」「）」
_DOI = re.compile(r'10\.\d{4,9}/[^\s\)\]\>"\'，。、）】]+')
# 推送日期：正文里形如 `_2026年8月1日 09:46_`，分隔符不固定，用非数字兜住
_DATE = re.compile(r'_(\d{4})\D(\d{1,2})\D(\d{1,2})\D')
# 非断行/短连字符 → 普通连字符（踩过：不换会白丢文献）
_HYPHENS = ('‑', '‐', '–')


def normalize_doi(doi):
    """规范化 DOI：去前缀、小写、去尾部标点、连字符归一。空的返回 ''。"""
    d = (doi or '').strip().lower().replace('https://doi.org/', '')
    for ch in _HYPHENS:
        d = d.replace(ch, '-')
    return d.rstrip('.').rstrip(')')


def extract(text):
    """一篇文章的正文 → (doi, pubdate)。抓不到的那一项返回 ''。"""
    m = _DOI.search(text or '')
    doi = normalize_doi(m.group(0)) if m else ''
    d = _DATE.search(text or '')
    pubdate = ''
    if d:
        try:
            pubdate = '%s-%02d-%02d' % (d.group(1), int(d.group(2)), int(d.group(3)))
        except ValueError:
            pubdate = ''
    return doi, pubdate


def journal_hint(filename):
    """从文件名开头猜期刊（下载工具的命名是「期刊名+中文标题」）。

    只是提示，不当真 —— 真正的期刊以 OpenAlex 为准。用途是人工抽查时好认。
    """
    base = os.path.splitext(os.path.basename(filename))[0]
    m = re.match(r'^([A-Za-z][A-Za-z\.\s]{1,30})', base)
    return (m.group(1).strip() if m else '')


def scan(directory):
    """扫一个公众号下载目录，返回种子列表。

    每项：{'file', 'doi', 'pubdate', 'journal_hint'}。
    **提不到 DOI 的也返回**（doi 为空），让调用方能报「多少篇不是论文推送」——
    这个数字是有意义的质量指标，不该在这里被悄悄吃掉。
    """
    if not os.path.isdir(directory):
        raise SeedError('公众号目录不存在: %s' % directory)
    names = sorted(n for n in os.listdir(directory) if n.lower().endswith('.md'))
    if not names:
        raise SeedError('目录里没有 .md 文件（下载时请只勾 md）: %s' % directory)
    out = []
    for n in names:
        p = os.path.join(directory, n)
        try:
            text = io.open(p, encoding='utf-8', errors='replace').read()
        except OSError as e:
            raise SeedError('读不了 %s: %s' % (n, e)) from e
        doi, pubdate = extract(text)
        out.append({'file': n, 'doi': doi, 'pubdate': pubdate,
                    'journal_hint': journal_hint(n)})
    return out


def stats(seeds):
    """种子列表 → 一行体检数字，便于调用方打印和报警。"""
    n = len(seeds)
    with_doi = sum(1 for s in seeds if s['doi'])
    dates = sorted(s['pubdate'] for s in seeds if s['pubdate'])
    return {'total': n, 'with_doi': with_doi,
            'doi_rate': (with_doi / n) if n else 0.0,
            'unique_doi': len(set(s['doi'] for s in seeds if s['doi'])),
            'earliest': dates[0] if dates else '', 'latest': dates[-1] if dates else ''}
