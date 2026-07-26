# -*- coding: utf-8 -*-
"""si_filter · SI（补充材料）内容过滤基础件（公理：SI全文 → 有价值段落）

职责：SI 价值密度高但噪声也大（作者名单、单位地址、目录清单、仪器型号）。
本件把 SI 正文按价值分档，滤掉零价值部分，只留合成细节与关键数据。

思路对齐前沿（MOF/reticular 合成挖掘的 paragraph classification），但**用规则不用LLM**——
因为"识别作者名单/单位/目录"这类模式是稳定的（宪法·稳定的自己做），零成本、可解释。

三档：
  - drop  丢弃：作者/单位/邮箱/目录清单(Figures S1-S23)/参考文献
  - core  核心：Materials / Synthesis / 制备流程 / 含定量数据的段落
  - brief 简要：仪器方法段（压缩成一行列出手段，不展开型号参数）

对外接口：
  - classify(text) → list[(kind, para)]
  - filtered_text(text) → str（可直接喂给精读/抽取的干净文本）
"""
import re

# 零价值：元信息
_DROP_PAT = re.compile(
    r'^\s*(\$\^?\{?\d|\*\s*Corresponding|Correspondence and requests|'
    r'Supporting Information\s*$|SI Materials and Methods\s*$|'
    r'(Figures?|Tables?|Movies?)\s+S\d+\s*[-–]\s*S?\d+\s*$|'
    r'(Figures?|Tables?|Movies?)\s+S\d+\s*$)', re.I)
# 作者行：必须是"人名, 人名"格式 + 上标，且**不含**科学内容特征
# （踩坑：原正则 (\$\^?\{?\d+\}?\$.*){2,} 太粗暴，误杀 ¹H NMR / ¹¹B NMR / 公式段）
_AUTHOR_PAT = re.compile(
    r'^[A-Z][a-z]+\s+[A-Z][a-z]+\s*\$\^?\{?[\d,]+\}?\$\s*,\s*[A-Z][a-z]+\s+[A-Z][a-z]+')
# 单位行：整段就是"编号. XX College/Institute of ..."的地址，而**非**试剂供应商说明
_AFFIL_PAT = re.compile(
    r'^\$?\^?\{?\d+\}?\$?\s*\.\s*(College|Institute|University|Laboratory|Department|'
    r'Academy|School|Center|Centre)\s+of', re.I)
# 参考文献区
_REF_PAT = re.compile(r'^\s*#{0,4}\s*(references?|bibliography)\s*$', re.I)
# 仪器方法段
_INSTR_PAT = re.compile(
    r'(spectra were|were (measured|recorded|performed|conducted|carried out) (on|with|using)|'
    r'instrument|spectrometer|analyzer|equipped with|calorimeter|diffractometer)', re.I)
# 含定量（合成参数的标志）
_QUANT_PAT = re.compile(r'\d+\s*(\.\d+)?\s*(g|mg|mL|μL|mmol|mol|wt%|v/v|°C|min|h)\b')
# 核心章节标题
_CORE_HEAD = re.compile(r'^\s*#{1,4}\s*(materials?|synthesis|preparation|fabrication|'
                        r'experimental|sample)', re.I)


# 保护：含这些特征的段落绝不丢弃（宁可多留，不可误杀关键数据）
_PROTECT_PAT = re.compile(
    r'(Mw\s*[=≈]|Mn\s*[=≈]|molecular weight|purchased|provided by|used as received|'
    r'\d+\s*(\.\d+)?\s*(g|mg|mL|mmol|mol)\b|Δ?E\s*\(|=\s*\\frac)', re.I)


def classify(text):
    """把 SI 文本按段落分档。返回 [(kind, para), ...]，kind ∈ drop/core/brief/keep。

    安全原则：含关键信息（分子量/试剂/定量/公式）的段落受保护，绝不丢弃。
    """
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    out = []
    in_refs = False
    for p in paras:
        if _REF_PAT.match(p):
            in_refs = True
        if in_refs:
            out.append(('drop', p)); continue
        protected = bool(_PROTECT_PAT.search(p))
        if not protected and (_DROP_PAT.match(p) or _AUTHOR_PAT.search(p) or _AFFIL_PAT.search(p)):
            out.append(('drop', p)); continue
        if _CORE_HEAD.match(p) or _QUANT_PAT.search(p):
            out.append(('core', p)); continue
        if _INSTR_PAT.search(p) and not protected:
            out.append(('brief', p)); continue
        out.append(('keep', p))     # 其余（图表题注、讨论、公式）默认保留
    return out


def _instrument_names(briefs):
    """从仪器方法段提炼手段名（如 FTIR / TGA / NMR），压成一行。"""
    names = []
    for p in briefs:
        m = re.match(r'\s*([A-Za-z][^:：\(]{2,60}?)\s*[:：\(]', p)
        if m:
            n = m.group(1).strip()
            if 2 < len(n) < 60 and n not in names:
                names.append(n)
    return names


def filtered_text(text, keep_instruments_brief=True):
    """产出过滤后的干净文本，供精读/抽取使用。"""
    parts = classify(text)
    kept, briefs = [], []
    for kind, p in parts:
        if kind == 'drop':
            continue
        if kind == 'brief':
            briefs.append(p); continue
        kept.append(p)
    body = '\n\n'.join(kept)
    if keep_instruments_brief and briefs:
        names = _instrument_names(briefs)
        if names:
            body += '\n\n## Characterization methods (condensed)\n' + '; '.join(names)
    return body


def stats(text):
    """统计各档段落数与字符数，用于评估过滤效果。"""
    parts = classify(text)
    from collections import Counter
    c = Counter(k for k, _ in parts)
    chars = {}
    for k in ('drop', 'core', 'brief', 'keep'):
        chars[k] = sum(len(p) for kk, p in parts if kk == k)
    return dict(counts=dict(c), chars=chars, total=len(text))
