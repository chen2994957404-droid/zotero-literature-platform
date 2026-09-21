# -*- coding: utf-8 -*-
"""units · 单位解析与量纲（包 Pint，2026-09-21 建）。

**解决的真实问题**：单位表靠手写永远补不全（范文 44% 的数曾因单位不认而没进候选），
而「这个数的单位」和「模型答的性质」对不对得上，是抽取里最便宜、最可靠的一道脚本把关：
拉伸强度必须是压强量纲，韧性必须是能量/体积，Tg 必须是温度 —— 「40 mm 是断裂韧性」这种错一票否决。

用户 2026-09-21 定的规矩：这类东西找现成库，别碰到一个补一个。Pint 自带几百个单位加全部词头，
我们实测的单位（MJ/m³、kcal/mol、mV/K、cd/m²、S/cm、cm⁻¹、°C、wt%…）全认。

第三方库只许住 adapters 这一环（硬规则 3）。使用者：tools/extract（抽取把关）、shared/domain/numcheck（数字核对，待接）。

对外接口：
    dimension(unit_text) → 量纲字符串（如 '[mass] / [length] / [time] ** 2'），认不出返回 ''
    same_dimension(a, b) → bool
    to_base(value, unit_text) → (换算后的值, 基本单位字符串) 或 None
    normalize_unit(unit_text) → Pint 认的写法（'MJ m-3' → 'MJ/m**3'）
"""
import re

_UREG = None


def _reg():
    global _UREG
    if _UREG is None:
        import pint
        _UREG = pint.UnitRegistry()
        _UREG.define('wtpercent = 0.01 = wt% = wt.% = wt_percent')
        _UREG.define('volpercent = 0.01 = vol% = vol_percent')
        _UREG.define('molpercent = 0.01 = mol% = mol_percent')
        _UREG.define('fold = [] = -fold = times')
        _UREG.define('ppm_ = 1e-6 = ppm')
    return _UREG


def normalize_unit(text):
    """论文里的写法 → Pint 认的写法：'MJ m-3' → 'MJ/m**3'，'cm-1' → 'cm**-1'，'°C' → 'degC'，'μm' → 'um'。"""
    t = (text or '').strip()
    low = t.lower().replace(' ', '')
    if low in ('wt%', 'wt.%', 'wt%.', 'wtpercent'):
        return 'wtpercent'
    if low in ('vol%', 'vol.%'):
        return 'volpercent'
    if low in ('mol%', 'mol.%'):
        return 'molpercent'
    if low in ('-fold', 'fold', 'times', 'x', '×'):
        return 'fold'
    t = t.replace('℃', 'degC').replace('°C', 'degC').replace('° C', 'degC').replace('µ', 'u').replace('μ', 'u').replace('·', '*')
    t = re.sub(r'\s*/\s*', '/', t)
    t = re.sub(r'([A-Za-z]+)\s*\^?\s*(-?\d)\b', r'\1**\2', t)          # m-3 / m^-3 / m2 → m**-3 / m**2
    t = re.sub(r'(?<=[A-Za-z0-9*])\s+(?=[A-Za-z])', '*', t)            # 'MJ m**-3' → 'MJ*m**-3'
    return t


def dimension(text):
    """单位文本 → 量纲字符串；认不出（或纯数）返回 ''。"""
    t = normalize_unit(text)
    if not t:
        return ''
    try:
        q = _reg().Quantity(1, t)
        return str(q.dimensionality)
    except Exception:
        return ''


def same_dimension(a, b):
    da, db = dimension(a), dimension(b)
    return bool(da) and da == db


def to_base(value, text):
    try:
        q = _reg().Quantity(float(value), normalize_unit(text)).to_base_units()
        return q.magnitude, str(q.units)
    except Exception:
        return None
