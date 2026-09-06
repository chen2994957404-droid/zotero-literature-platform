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

所以**方向库只吃 DOI + 推送日期**：库建在 OpenAlex 的 DOI 上，不建在微信上。
明天工具挂了，换掉这一个文件就行，地图照常运转。

## 2026-09-06 改：正文不再「提完即弃」

用户定的：**推送正文本身就是一份高质量的中文正文精读**（我们自己的精读一直在
照它学），既然取 PDF 的通道通了，就反过来用 —— 推文当正文精读，我们只补 SI。
于是本块多了 `parse_article()` / `fetch_image()`。

边界没变：**只有被显式导入的那几篇才会落盘**（`host/wechat_import`），
批量扫描仍然只吃 DOI。方向库那条线一个字都没动。

## 实测数据（835 篇，2025-01-28 ~ 2026-08-28）

    文章 835 → 有 DOI 769（92.1%）→ OpenAlex 命中 754（占全部 90.3%）
    提不到 DOI 的那 66 篇基本不是论文推送（会议邀请、招聘、报到通知、营销文），
    **本来就该丢掉，而且是自动丢的**。

两个踩过的坑，都固化在代码里：

1. **DOI 里有非断行连字符 U+2011**，不归一化成 `-` 会白丢几篇。
2. 文件名形如 `期刊名+中文标题.md`，**不带日期**；日期在正文里
   （`_2026年8月1日 09:46_`），所以日期只能从正文抓。

对外接口：
    scan(dir)          → [{file, doi, pubdate, journal_hint}]，按文件名排序
    extract(text)      → (doi, pubdate)，单篇，纯函数便于测试
    parse_article(t)   → {title, doi, pubdate, blocks}，整篇拆成段落 + 图（纯函数）
    fetch_image(url)   → (bytes, content_type)，**本块唯一联网的函数**

依赖：标准库。除 `fetch_image` 外都不联网 —— 读的是别人下载好的本地文件。
（放在 adapters 环，本来就是因为它是「外部世界的形状」的适配点。）
"""
import io
import os
import re

from shared.kernel import errors


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


# ── 取正文（2026-09-06 加）───────────────────────────────────────────
# 起因：推送本身就是一份高质量的中文正文精读，用户决定直接拿来当正文精读用。
# 于是本块的职责从「只提 DOI」扩到「把一篇推送拆成标题 + 段落 + 图」。
# 仍然只认**外部世界的形状**：微信改排版就只改这里。

# 平台自己的噪音行（实测量出来的，不是猜的）。整行完全等于才算，避免误伤正文。
_JUNK_LINES = frozenset([
    '在小说阅读器读本章', '去阅读', '预览时标签不可点', '阅读', '知道了',
    '取消  允许', '取消 允许', '继续滑动看下一个', '轻触阅读原文',
    '向上滑动看下一个', '****', '__', '', '_ _',
])
_IMG = re.compile(r'^!\[[^\]]*\]\(([^)\s]+)')
# 署名行：`原创  X  Y  公众号名` / 日期行：`_2026年08月17日 08:34_ ...`
_BYLINE = re.compile(r'^(原创\s|_\d{4}年)')


def _is_junk(line):
    s = line.strip()
    return (s in _JUNK_LINES) or bool(_BYLINE.match(s)) or set(s) <= set('_ *')


def _join(lines):
    """把被硬折行的一段拼回一句：两边都是 ASCII 才补空格（中文之间不补）。"""
    out = ''
    for ln in lines:
        ln = ln.strip()
        if not out:
            out = ln
            continue
        if out[-1].isascii() and ln[:1].isascii():
            out += ' ' + ln
        else:
            out += ln
    return out


def parse_article(text):
    """一篇推送的 md → dict(title, doi, pubdate, blocks)。

    `blocks` 是按原顺序的正文流：`{'kind':'p','text':...}` 或 `{'kind':'img','url':...}`。

    **头尾的平台噪音与品牌图会被剥掉**：正文从第一个实质段落开始，到写着 DOI
    的那一行为止。这个边界是实测出来的 —— 公众号的头图、名片图、二维码都落在
    这个区间之外，而文献配图全在区间之内。宁可少要几张图，不能把二维码当成图 3。
    """
    text = text or ''
    doi, pubdate = extract(text)
    lines = text.splitlines()
    title = ''
    for ln in lines:
        if ln.startswith('#'):
            title = ln.lstrip('#').strip()
            break

    # 终点：DOI 出现在哪一行（正文里也可能出现，取最后一次，那才是文末的出处行）
    end = len(lines)
    if doi:
        for i, ln in enumerate(lines):
            if doi in normalize_doi_line(ln):
                end = i
    raw, started = [], False
    for ln in lines[:end]:
        s = ln.strip()
        if s.startswith('#') or _is_junk(s):
            continue
        m = _IMG.match(s)
        if m:
            if started:                      # 正文没开始 = 还在头图区，丢掉
                raw.append(('img', m.group(1)))
            continue
        # 实质段落：去掉 md 的加粗记号后仍有内容
        started = True
        raw.append(('p', s.replace('**', '').strip()))

    # 把连续的 p 行合并成段（空行已在 _JUNK_LINES 里被吃掉，所以按 img 切段）
    blocks, buf = [], []
    for kind, val in raw:
        if kind == 'p':
            buf.append(val)
        else:
            if buf:
                blocks.append({'kind': 'p', 'text': _join(buf)})
                buf = []
            blocks.append({'kind': 'img', 'url': val})
    if buf:
        blocks.append({'kind': 'p', 'text': _join(buf)})
    blocks = [b for b in blocks if b['kind'] == 'img' or len(b.get('text', '')) > 1]
    return {'title': title, 'doi': doi, 'pubdate': pubdate, 'blocks': blocks}


def normalize_doi_line(line):
    """一行文本里的 DOI 归一后原样返回（找文末出处行用）。

    单独一个函数是因为文末写的是 `https://doi.org/  10.1021/xxx`（**中间有空格**），
    直接 `doi in line` 找不到。
    """
    return normalize_doi((line or '').replace('https://doi.org/', '').strip())


def fetch_image(url, timeout=20):
    """下载一张推文配图 → bytes。失败抛 SeedError（调用方决定是否跳过这张）。

    实测（2026-09-06）：微信图床 `mmbiz.qpic.cn` **没有防盗链**，裸请求即 200。
    所以这里不伪造 Referer —— 少一层将来会悄悄失效的假设。
    """
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            ctype = r.headers.get('Content-Type', '')
    except Exception as e:
        raise SeedError('取图失败 %s: %s' % (url[:60], e)) from e
    if not data or not ctype.startswith('image/'):
        raise SeedError('取回来的不是图片（%s）: %s' % (ctype, url[:60]))
    return data, ctype
