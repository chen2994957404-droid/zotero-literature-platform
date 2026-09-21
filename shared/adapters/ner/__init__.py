# -*- coding: utf-8 -*-
"""ner · 零样本命名实体识别（包 GLiNER，2026-09-21 建）。

**解决的真实问题**：样品名 / 材料名靠「大写缩写正则 + 表格行首」认，多词样品（PVA/CPO eutectogel）认不出，
抽取里样品归属只对了 52%。GLiNER 是零样本 NER 小模型（medium 版约 200M 参数，CPU 0.2 s/句），
给标签名（sample code / material / reagent）就能标，不用训练。编程端实测 5 句：FC-EtFe、PVA/CPO eutectogel、
P1-BF4、CAN-4-3-30、PBA-diol、IPDI 全标出来了。

第三方库只许住 adapters 这一环（硬规则 3）。使用者：tools/extract（样品名单）、tools/deepread（术语表补样品，待接）。
模型名走配置 `NER_MODEL`（默认 urchade/gliner_medium-v2.1）；第一次用会从 Hugging Face 下载（约 1 GB）。

对外接口：
    entities(text, labels, threshold=0.4) → [{'text','label','score','start','end'}]
    sample_mentions(text, threshold=0.4) → 按出现顺序去重的样品 / 材料名列表
    alive() → 模型能不能加载（自测与体检用；不联网时可能 False）
"""
import re

SAMPLE_LABELS = ('sample code', 'material', 'reagent')
_MODEL = {'obj': None, 'name': ''}


def _model_name():
    from shared.kernel.config import get_key
    return get_key('NER_MODEL', default='urchade/gliner_medium-v2.1')


def _model():
    if _MODEL['obj'] is None:
        from gliner import GLiNER
        _MODEL['name'] = _model_name()
        _MODEL['obj'] = GLiNER.from_pretrained(_MODEL['name'])
    return _MODEL['obj']


def entities(text, labels=SAMPLE_LABELS, threshold=0.3):
    if not (text or '').strip():
        return []
    out = []
    for e in _model().predict_entities(text[:3000], list(labels), threshold=threshold):
        out.append({'text': e['text'], 'label': e['label'], 'score': round(float(e['score']), 3),
                    'start': int(e['start']), 'end': int(e['end'])})
    return out


_NOISE = re.compile(r'^(\d+(\.\d+)?%?|[a-z]{1,2}|inc\.?|ltd\.?|co\.?|sigma|aldrich|gelest|merck|tci|alfa aesar)$', re.I)


_CODE = re.compile(r'\b[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+){1,3}\b')     # FC-EtFe、P1-BF4、CAN-4-3-30 这类样品编号（P1-BF4 只有一个大写字母开头）


def sample_mentions(text, threshold=0.3):
    """窗口里提到的样品 / 材料 / 试剂名，按出现顺序去重；纯数字、供应商名这类噪声剔掉。

    GLiNER 对短句里的编号（FC-Et）分数只有 0.4–0.5、偶尔漏 —— 所以跟样品编号正则取**并集**：
    正则兜住编号，GLiNER 兜住多词名（PVA/CPO eutectogel）。
    """
    found = [(e['start'], e['text'], e['label'] == 'sample code') for e in entities(text, threshold=threshold)]
    found += [(m.start(), m.group(0), True) for m in _CODE.finditer(text or '')]
    seen, codes, others = set(), [], []
    for _, t, is_code in sorted(found):
        t = t.strip(' ,;()')
        if len(t) < 2 or _NOISE.match(t) or t.lower() in seen:
            continue
        seen.add(t.lower())
        (codes if is_code or _CODE.search(t) else others).append(t)
    return codes + others                      # 编号样的排前面：它们才是「样品」，后面的多半是基底 / 试剂 / 材料类名


def alive():
    try:
        _model()
        return True
    except Exception:
        return False
