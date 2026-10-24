# -*- coding: utf-8 -*-
"""embed · 文本向量化基础件（原子能力：文本 → 向量 + 文本预处理原子操作）

职责：把文本转成向量（bge-m3 本地嵌入模型），以及向量化前的通用文本预处理
（去参考文献、切块）。此前 embed/strip_references/chunk 在 vectorize.py 和
vectorize_library.py 各有一份重复拷贝，收敛成单一原子模块。

原子模块的特征：embedding 只做「文本→向量」的映射，不理解内容。
strip_references / chunk 是可复用的文本预处理原子操作。

对外接口：
  - embed(texts)              → list[向量]（批量）
  - strip_references(text)    → 去掉参考文献及之后部分的正文
  - chunk(text, max_chars)    → list[文本块]（按段落切，去图片标记）

配置：本机 Ollama（OLLAMA_HOST，控制面板可改）+ 模型 EMBED_MODEL（默认 bge-m3）。
  2026-10-24 平台不再调生成式大模型，路由表随之撤掉，向量化回到只走本地。
  ⚠ 换嵌入模型 = 整个向量库要重建（两家的向量互不兼容）。
"""
import os, re, json, urllib.request

_DEFAULTS = {'OLLAMA_HOST': 'http://localhost:11434'}
try:
    from shared.kernel.config import get_site as _cfg_site
except Exception:                      # 模块要能被单独拷走用，取不到 config 就退回环境变量
    _cfg_site = lambda n: os.environ.get(n) or _DEFAULTS.get(n, '')


def _host():
    # 地址走 config（控制面板「Ollama 地址」可改），不再写死（强制规范 #3）
    return (_cfg_site('OLLAMA_HOST') or _DEFAULTS['OLLAMA_HOST']).rstrip('/')


def _model():
    try:
        from shared.kernel.config import get_key
        return get_key('EMBED_MODEL', default='bge-m3')
    except Exception:
        return os.environ.get('EMBED_MODEL', 'bge-m3')


def embed(texts):
    """批量文本 → 向量（本机 Ollama 的 /api/embed）。texts 是 str 列表，返回等长的向量列表。"""
    body = json.dumps({'model': _model(), 'input': texts}).encode()
    req = urllib.request.Request(_host() + '/api/embed', data=body,
                                 headers={'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=300).read())['embeddings']


def embed_batched(texts, size=48, max_chars=1200):
    """分批、截长的 embed：Ollama 的 /api/embed 一次塞几百条会 400（2026-09-21 实测）；单批再失败就逐条，逐条也失败给 [0.0] 占位。"""
    out = []
    for i in range(0, len(texts), size):
        batch = [t[:max_chars] for t in texts[i:i + size]]
        try:
            out += embed(batch)
        except Exception:
            for t in batch:
                try:
                    out += embed([t])
                except Exception:
                    out.append([0.0])
    return out


def cosine(a, b):
    if len(a) != len(b) or len(a) < 2:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def strip_references(text):
    """截掉参考文献及之后部分（References/Bibliography/参考文献/Supporting Information），
    只留正文，让检索聚焦研究内容。截得太狠（正文<20%）则退回原文（防误截）。"""
    pat = re.compile(r'(?im)^\s*#{0,4}\s*(references|reference|bibliography|参考文献|literature\s+cited)\s*$')
    m = pat.search(text)
    cut = m.start() if m else len(text)
    sm = re.search(r'(?im)^\s*#{1,4}\s*supporting\s+information\s*$', text)
    if sm and sm.start() < cut:
        cut = sm.start()
    body = text[:cut].strip()
    return text if len(body) < len(text) * 0.2 else body


def chunk(text, max_chars=800):
    """按段落切块，合并短段、切超长段，去参考文献与图片标记。返回文本块列表。"""
    text = strip_references(text)
    text = re.sub(r'!\[\]\(images/[^)]+\)', '', text)
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    chunks, cur = [], ''
    for p in paras:
        if len(cur) + len(p) < max_chars:
            cur += ('\n' + p) if cur else p
        else:
            if cur:
                chunks.append(cur)
            if len(p) > max_chars:
                for i in range(0, len(p), max_chars):
                    chunks.append(p[i:i+max_chars])
                cur = ''
            else:
                cur = p
    if cur:
        chunks.append(cur)
    return chunks


def alive(timeout=6):
    """Ollama 通不通（探活也是联网，所以放在适配层，强制规范 #5）。

    R3 窗收进来的：库房维护的定时同步原本自己 urlopen 探 /api/tags。
    """
    try:
        urllib.request.urlopen(_host() + '/api/tags', timeout=timeout)
        return True
    except Exception:
        return False
