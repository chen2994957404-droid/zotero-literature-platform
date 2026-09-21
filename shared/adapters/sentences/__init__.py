# -*- coding: utf-8 -*-
"""sentences · 句子切分（包 pySBD，2026-09-21 建）。

**解决的真实问题**：切句的正则 + 缩写表项目里写了两份（zoning、fine_fact），Fig. / ref. / et al. / vs. / e.g. 这些
永远补不全。pySBD 是规则式句边界消歧库，专门处理这些（实测五种缩写全对，且给字符位置）。
用户 2026-09-21 定：这类东西找现成库，别碰到一个补一个。

第三方库只许住 adapters（硬规则 3）。使用者：tools/extract（找数所在的句子）、tools/extract/zoning（分区）。

对外接口：
    split(text, lang='en') → [(start, end, sentence)]，位置对应原文
    sentence_at(text, pos, lang='en') → 包含 pos 的那一句（找不到返回 ''）
"""
_SEG = {}


def _seg(lang):
    if lang not in _SEG:
        import pysbd
        _SEG[lang] = pysbd.Segmenter(language=lang, clean=False, char_span=True)
    return _SEG[lang]


def split(text, lang='en'):
    if not (text or '').strip():
        return []
    out = []
    for s in _seg(lang).segment(text):
        sent = s.sent.strip()
        if sent:
            out.append((s.start, s.end, sent))
    return out


def sentence_at(text, pos, lang='en'):
    """包含 pos 的那一句。pySBD 按段跑：先找 pos 所在的段（空行分隔），只切那一段，省时间。"""
    if not text:
        return ''
    a = text.rfind('\n\n', 0, pos)
    a = 0 if a < 0 else a + 2
    b = text.find('\n\n', pos)
    b = len(text) if b < 0 else b
    para = text[a:b]
    for s, e, sent in split(para, lang):
        if a + s <= pos < a + e:
            return ' '.join(sent.split())
    return ' '.join(para.split())[:600]
