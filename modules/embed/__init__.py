# -*- coding: utf-8 -*-
"""embed · 文本向量化基础件（公理：文本 → 向量 + 文本预处理原子操作）

职责：把文本转成向量（bge-m3 本地嵌入模型），以及向量化前的通用文本预处理
（去参考文献、切块）。此前 embed/strip_references/chunk 在 vectorize.py 和
vectorize_library.py 各有一份重复拷贝，收敛成单一公理件。

公理特征：embedding 只做「文本→向量」的映射，不理解内容（区别于 llm_client 的生成）。
strip_references / chunk 是可复用的文本预处理原子操作。

对外接口：
  - embed(texts)              → list[向量]（批量）
  - strip_references(text)    → 去掉参考文献及之后部分的正文
  - chunk(text, max_chars)    → list[文本块]（按段落切，去图片标记）

配置（环境变量）：
  - EMBED_MODEL : 默认 bge-m3
  - OLLAMA_HOST : 默认 http://localhost:11434
"""
import os, re, json, urllib.request

_DEFAULTS = {'OLLAMA_HOST': 'http://localhost:11434'}
try:
    import sys as _s2, os as _o2
    _s2.path.insert(0, _o2.path.dirname(_o2.path.dirname(_o2.path.abspath(__file__))))
    from modules.config import get_site as _cfg_site
except Exception:                      # 积木要能被单独拷走用，取不到 config 就退回环境变量
    _cfg_site = lambda n: __import__('os').environ.get(n) or _DEFAULTS.get(n, '')


def _embed_url():
    # 地址走 config（控制面板「Ollama 地址」可改），不再写死（红线 #3）
    host = _cfg_site('OLLAMA_HOST') or _DEFAULTS['OLLAMA_HOST']
    return host + '/api/embed'


def embed(texts):
    """批量文本 → 向量。texts 是 str 列表，返回等长的向量列表。"""
    model = os.environ.get('EMBED_MODEL', 'bge-m3')
    body = json.dumps({'model': model, 'input': texts}).encode()
    req = urllib.request.Request(_embed_url(), data=body,
                                 headers={'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=300).read())['embeddings']


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
