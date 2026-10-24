# -*- coding: utf-8 -*-
"""props · 性能名字归一 + 「性能: 数 单位」拆成能比大小的数（纯逻辑，给 scan 用）。

原来住在结构化抽取的 schema 里；2026-10-24 抽取整套删掉后，只有骨架的数字 / 表格扫描还要这两样，
就把它们单独留在这里，其余（字段表、提示词、出表）随抽取一起删了。

对外接口：
  - PROPERTY_ALIASES / normalize_property_name : 性能名字的统一词表与归一
  - parse_property / tidy_unit                 : 'tensile strength: 12 MPa' → {name, value, unit, cmp, value_max}
"""
import functools
import re


# ── 性能名字的统一词表 ────────────────────────────────────────────────
# 为什么必须归一：模型每篇写法都不一样（tensile strength / ultimate tensile
# stress / 拉伸强度 / σb）。不归一，「强度>10 MPa」这一句 SQL 就漏掉一半的库。
# **只归一名字，绝不归一单位**（单位换算错比查不到更难发现）。
PROPERTY_ALIASES = {
    'tensile strength':      ('tensile strength', 'ultimate tensile strength', 'ultimate tensile stress',
                              'tensile stress', 'fracture strength', 'breaking strength', 'strength at break',
                              '拉伸强度', '断裂强度'),
    'elongation at break':   ('elongation at break', 'strain at break', 'fracture strain', 'breaking elongation',
                              'elongation', '断裂伸长率', '断裂应变'),
    "young's modulus":       ("young's modulus", 'youngs modulus', 'elastic modulus', 'tensile modulus',
                              'modulus', '弹性模量', '杨氏模量'),
    'storage modulus':       ('storage modulus', "g'", '储能模量'),
    'loss modulus':          ('loss modulus', 'g"', '损耗模量'),
    # ⚠ 'energy dissipation' 从这里挪走了（2026-09-08）：耗散能与韧性是两个量，
    # 混在一起会让「这个体系耗散了多少能量」和「它有多韧」在库里变成同一列。
    'toughness':             ('toughness', 'work of fracture', 'fracture energy',
                              'tensile toughness', '韧性'),
    'self-healing efficiency': ('self-healing efficiency', 'self healing efficiency', 'healing efficiency',
                                'recovery efficiency', '自修复效率', '修复效率'),
    'mn':                    ('mn', 'number average molecular weight', 'number-average molecular weight'),
    'mw':                    ('mw', 'weight average molecular weight', 'weight-average molecular weight'),
    'pdi':                   ('pdi', 'polydispersity', 'polydispersity index', 'dispersity'),
    'viscosity':             ('viscosity', 'complex viscosity', 'zero-shear viscosity', 'shear viscosity', '粘度'),
    'glass transition temperature': ('glass transition temperature', 'tg', '玻璃化转变温度'),
    'thermal stability':     ('thermal stability', 'decomposition temperature', 'td', 't5%', '热分解温度'),
    'conductivity':          ('conductivity', 'ionic conductivity', 'electrical conductivity', '电导率', '离子电导率'),
    'gauge factor':          ('gauge factor', 'sensitivity', 'gf', '灵敏度'),
    'adhesion strength':     ('adhesion strength', 'adhesive strength', 'lap shear strength', 'lap-shear strength', 'peel strength',
                              'wet shear strength', 'dry shear strength', 'bonding strength', 'adhesion force',
                              '粘接强度', '剥离强度', '粘附强度', '黏附强度', '粘合强度', '搭接剪切强度', '湿剪切强度', '干剪切强度'),
    'hardness':              ('hardness', 'shore hardness', '硬度'),
    'impact strength':       ('impact strength', 'impact resistance', 'impact energy', 'ballistic limit',
                              '冲击强度', '抗冲击'),
    'crosslink density':     ('crosslink density', 'cross-link density', '交联密度'),
    # ── 论文里的符号名（2026-09-08 加，金标量出来的）────────────────────
    # 作者常只在正文里定义一次符号（`the plateau elastic modulus, Ge`），
    # 之后整篇都用符号。抽取时照抄符号是**正确行为**，词表不认就会被判成错标。
    'plateau elastic modulus': ('plateau elastic modulus', 'plateau modulus', 'ge',
                                'ge,exp', 'ge,fit', 'g_e', 'g_e,exp', 'g_e,fit',
                                'gn0', '平台模量'),
    'relaxation time':       ('relaxation time', 'characteristic relaxation time',
                              'tauc', 'tau_c', 'tau c', 'τc', 'τ_c', 'τ', '松弛时间'),
    'dissipated energy':     ('dissipated energy', 'energy dissipation', 'wd', 'w_d',
                              'hysteresis energy', '耗散能'),
    'energy dissipation ratio': ('energy dissipation ratio', 'dissipation ratio',
                                 'denergy', 'd_energy', '耗散比'),
    'detection limit':       ('detection limit', 'limit of detection', 'lod',
                              'detection limit (aq.)', '检出限'),
    'ceramic yield':         ('ceramic yield', 'char yield', 'residual mass',
                              '陶瓷产率', '残炭率'),
    # ── 2026-09-21 用数据造的那一批（1070 篇原文 + 774 篇范文里数值前的性质短语，本地 9.7B 归一，我复核）──
    # 用户定的规矩：词表别靠碰到一个补一个；这批是按频次统计出来的，频次 ≥3 的中文短语与 ≥5 的英文短语全在里面。
    'compressive strength':  ('compressive strength', 'compression strength', '压缩强度'),
    'compressive modulus':   ('compressive modulus', 'compression modulus', '压缩模量'),
    'flexural strength':     ('flexural strength', 'bending strength', '弯曲强度'),
    'flexural modulus':      ('flexural modulus', 'bending modulus', '弯曲模量'),
    # 搭接剪切（lap shear）是粘接的量法，归 adhesion strength（上面已有）；这里只收材料本体的剪切强度
    'shear strength':        ('shear strength', 'interfacial shear strength', '剪切强度', '界面剪切强度'),
    'shear modulus':         ('shear modulus', '剪切模量'),
    'yield strength':        ('yield strength', 'yield stress', '屈服强度'),
    'fracture energy':       ('fracture energy', 'work of fracture', '断裂能'),
    'fracture toughness':    ('fracture toughness', '断裂韧性'),
    'specific strength':     ('specific strength', '比强度'),
    'recovery ratio':        ('recovery ratio', 'recovery rate', 'shape recovery ratio', 'shape recovery', 'rebound rate',
                              'rebound resilience', 'resilience', '回复率', '恢复率', '回弹率', '落球回弹率'),
    'shape fixity ratio':    ('shape fixity ratio', 'shape fixity', '形状固定率'),
    'residual strain':       ('residual strain', 'permanent set', '残余应变'),
    "poisson's ratio":       ("poisson's ratio", 'poissons ratio', 'poisson ratio', '泊松比'),
    'crystallinity':         ('crystallinity', 'degree of crystallinity', 'crystalline content', '结晶度', '晶体含量'),
    'melting temperature':   ('melting temperature', 'melting point', 'tm', '熔融温度', '熔点'),
    'melting enthalpy':      ('melting enthalpy', 'enthalpy of fusion', 'heat of fusion', 'δhm', 'dhm', '熔融焓'),
    'decomposition temperature': ('decomposition temperature', 'onset decomposition temperature', 'initial decomposition temperature',
                                  'temperature of onset of weight loss', 'maximum thermal degradation temperature', 'tonset', 'tmax',
                                  '热分解温度', '分解温度', '初始分解温度', '热失重温度', '最大热降解温度'),
    'thermal conductivity':  ('thermal conductivity', '导热系数', '热导率'),
    'transmittance':         ('transmittance', 'transparency', 'optical transmittance', 'light transmittance', '透光率', '透过率'),
    'reflectance':           ('reflectance', 'reflectivity', 'solar reflectance', '反射率', '太阳反射率'),
    'water content':         ('water content', '含水量', '含水率'),
    'water absorption':      ('water absorption', 'water absorption rate', 'water uptake', '吸水率'),
    'swelling ratio':        ('swelling ratio', 'swelling degree', 'degree of swelling', '溶胀率', '溶胀比'),
    'gel fraction':          ('gel fraction', 'gel content', '凝胶分数', '凝胶含量'),
    'porosity':              ('porosity', '孔隙率'),
    'contact angle':         ('contact angle', 'water contact angle', 'wca', '接触角', '水接触角'),
    'surface roughness':     ('surface roughness', 'roughness', 'ra', 'rms roughness', '表面粗糙度', '粗糙度'),
    'activation energy':     ('activation energy', 'ea', 'e_a', '活化能'),
    'capacity retention':    ('capacity retention', 'capacity retention rate', 'capacitance retention', '容量保持率', '次循环容量保持率', '电容保持率'),
    'coulombic efficiency':  ('coulombic efficiency', 'average coulombic efficiency', '库仑效率', '平均库仑效率'),
    'energy density':        ('energy density', '能量密度'),
    'power density':         ('power density', '功率密度'),
    'mobility':              ('mobility', 'carrier mobility', 'ion mobility', '迁移率'),
    'recovery of monomer':   ('monomer recovery', 'monomer recovery rate', 'recovery yield', '单体回收率', '回收率'),
    'degradation rate':      ('degradation rate', 'degradation ratio', 'weight loss', '降解率', '失重率'),
    'conversion':            ('conversion', 'conversion rate', 'monomer conversion', '转化率'),
    'degree of substitution': ('degree of substitution', 'degree of deacetylation', 'degree of hydrolysis', 'degree of alcoholysis',
                               '取代度', '脱乙酰度', '水解度', '醇解度'),
    'cell viability':        ('cell viability', 'viability', '细胞存活率', '存活率'),
    'sensing range':         ('sensing range', 'detection range', 'working range', '传感范围', '检测范围'),
    'response time':         ('response time', 'recovery time', '响应时间'),
    'dielectric constant':   ('dielectric constant', 'permittivity', 'relative permittivity', '介电常数'),
    'ionic conductivity':    ('ionic conductivity', '离子电导率'),
    'hydrogel conductivity': ('hydrogel conductivity',),
    'volume fraction':       ('volume fraction', '体积分数'),
    'mass fraction':         ('mass fraction', 'weight fraction', '质量分数'),
    'fiber content':         ('fiber content', 'filler content', '纤维含量', '填料含量'),
    'crosslinker content':   ('crosslinker content', 'cross-linker content', '交联剂含量'),
    'retention':             ('retention', 'retention rate', 'residual ratio', '保留率', '残留率'),
    'correlation length':    ('correlation length', '相关长度'),
    'thermal hysteresis':    ('thermal hysteresis', '热滞'),
    'lifetime':              ('lifetime', 'service life', 'cycle life', 'cycling stability', '寿命', '循环寿命'),
}


# 反查表：别名 → 正名。长别名优先匹配（'ultimate tensile strength' 要盖过 'tensile strength'）
_ALIAS_TO_CANON = sorted(
    ((a, canon) for canon, alist in PROPERTY_ALIASES.items() for a in alist),
    key=lambda x: -len(x[0]))


# 别名 → 编译好的「整词匹配」正则，只编一次（原来每次调用都对几百个别名现 escape + 现编，
# 数值库重建时调 13 万次，占了重建的大半时间 —— 2026-09-30 在 B 机上 profile 出来的）
_ALIAS_RES = [(re.compile(r'(^|[^a-z])' + re.escape(a) + r'($|[^a-z])'), a, canon) for a, canon in _ALIAS_TO_CANON]


def normalize_property_name(name):
    """性能名字 → 统一词表里的正名；词表里没有的原样返回（小写去空白）。

    **只做名字归一，不碰单位、不碰数值。**词表外的名字照样入库 ——
    宁可库里多几个没归一的名字，也不要把它们悄悄丢掉。
    纯函数，按名字缓存（6 万条数值里名字只有几千种）。
    """
    return _normalize_property_name(str(name or ''))


@functools.lru_cache(maxsize=None)
def _normalize_property_name(name):
    t = re.sub(r'\s+', ' ', str(name or '')).strip().lower().strip('（）()[]:：')
    if not t:
        return ''
    if t in PROPERTY_ALIASES:
        return t
    for rx, alias, canon in _ALIAS_RES:
        if alias == t or rx.search(t):
            return canon
    return t


# ── 性能数值：字符串 → 能比大小的数 ────────────────────────────────────
# 为什么要这一步（2026-08-28，数据库方向③）：
#     key_properties 里存的是 'tensile strength: 12 MPa' 这种人话。
#     人能看，机器比不了大小 —— 「拉伸强度 > 10 MPa 的都有哪些」这类问题
#     只要还停在字符串上就永远答不了。把它拆成 (名字, 数, 单位) 才能进查询库。
# **不做单位换算**：MPa 与 kPa 混在一起时宁可让人看见，也不偷偷换算错。
# （数值库 tools/paperdb 2026-10-23 删了；现在只给 scan 数「这节有几个数、表里有几行」用。）

_NUM = (r'([-+]?\d+(?:[.,]\d+)?)'                    # 3.2
        r'(?:\s*[eE]([-+]?\d+)'                      # 3.2e-5
        r'|\s*[×xX*]\s*10\s*\^?\s*([-+]?\d+)'      # 3.2 × 10^4
        r'|\s*[×xX*]\s*10\s*([-+−]\d+))?')           # 3.2 × 10-5（上标丢了的情形）
_CMP = r'([~≈><≥≤]|about|approx\.?|up to|over|more than|less than)?\s*'
_PROP_RE = re.compile(r'(?i)^\s*' + _CMP + _NUM)
_RANGE_RE = re.compile(_NUM + r'\s*[–—\-~]\s*' + _NUM)

_CMP_MAP = {'~': '~', '≈': '~', 'about': '~', 'approx': '~', 'approx.': '~',
            '>': '>', 'over': '>', 'more than': '>', 'up to': '<',
            '<': '<', 'less than': '<', '≥': '>', '≤': '<'}


def _to_float(m, base=1):
    """把匹配到的「数 + 指数」拼成一个 float；拼不出来返回 None。"""
    try:
        v = float(str(m.group(base)).replace(',', ''))
    except (TypeError, ValueError):
        return None
    for g in (base + 1, base + 2, base + 3):
        exp = m.group(g)
        if exp:
            try:
                v *= 10 ** int(str(exp).replace('−', '-'))
            except ValueError:
                return None
            break
    return v


# ── 单位要洗干净再入库 ────────────────────────────────────────────────
# 2026-09-08 实测：`parse_property` 把数字后面的**一整截话**都当成了单位，
# 于是库里出现了 `'% in the first cycle to '`、`'h of healing'`、`'% to 15%'`
# 这种「单位」。后果不是难看，是**同一个数被算成两条**：
#   `1484.9 mJ mm-1` 与 `1484.9 mJ mm -1` 去重时对不上号。
# 云端模型和本地模型都会这样写 —— 这是**我们的解析太宽**，不是谁笨。
#
# 三条规则，都不需要「理解」：
#   1. 指数前的空格去掉：`kJ m -2` → `kJ m-2`
#   2. 遇到英文虚词就截断：`% in the first cycle` → `%`
#   3. 同一个符号连着重复的收成一个：`% %` → `%`
_UNIT_STOP = re.compile(
    r'\s+(?:to|in|at|of|on|for|after|and|or|with|the|an?|when|while|under|'
    r'over|from|by|which|that|its?|was|were|is|are)(?![a-z]).*$', re.I)


def tidy_unit(unit):
    """单位串洗干净。洗不出东西就返回空串（**空单位好过假单位**）。"""
    u = re.sub(r'\s+', ' ', str(unit or '')).strip().strip('.,;:')
    if not u:
        return ''
    u = _UNIT_STOP.sub('', u).strip()
    u = re.sub(r'\s+(?=[-−+]\s*\d)', '', u)      # kJ m -2 → kJ m-2
    u = re.sub(r'([-−+])\s+(\d)', r'', u)      # kJ m- 2 → kJ m-2
    parts = u.split()
    if len(parts) > 1 and len(set(parts)) == 1:   # '% %' → '%'
        u = parts[0]
    return u.strip().strip('.,;:')[:24]

# 光杆幂次：`10^-10 M` → `1×10^-10 M`（2026-09-08 加）。
# 为什么必须在这里也做一遍：`scan.clean_body` 洗的是**正文**，
# 而模型是照着正文抄给我们的 —— 它抄回来的 `10^-10` 不经过那一步。
# 不认的后果不是报错，是**读成 10**：检出限 1e-10 M 会变成 10 M，
# 一个错了十个数量级、却长得完全正常的数字。
# 科学计数法的各种写法 → 解析器认得的那一种（2026-09-08 加）。
# **一条正则同时管两种**：`1.2 × 10^4` 与光杆的 `10^-10`（系数省略 = 1）。
# 分成两条会互相踩：先补光杆的那条会把 `1.2 x 10^4` 里的 `10^4` 也补上系数，
# 变成 `1.2 x 1×10^4`，值被读成 1.2 —— 实测踩过。
#
# 为什么在这里也要做：`scan.clean_body` 洗的是**正文**，而模型是照着正文抄给我们的，
# 它抄回来的 `10^-10` 不经过那一步。不认的后果不是报错，是**读成 10** ——
# 检出限 1e-10 M 变成 10 M，一个错了十个数量级、却长得完全正常的数字。
_SCI_POW = re.compile(
    r'(?<![\d.\w])(?:(\d+(?:\.\d+)?)\s*[×xX*]\s*)?10\s*\^\s*([-+−]?\d+)')


def _norm_pow(text):
    return _SCI_POW.sub(
        lambda m: (m.group(1) or '1') + chr(215) + '10^'
        + m.group(2).replace(chr(8722), '-'), text)


def parse_property(text):
    """`'tensile strength: 12 MPa'` → `{'name','value','unit','cmp','value_max','raw'}`。

    拆不出数字时 value 为 None（`'self-healing: yes'` 这种照样保留，
    只是不能参与大小比较）。**不换算单位**，unit 原样留着。
    """
    raw = _norm_pow(str(text).strip())
    name, _, rest = raw.partition(':')
    if not rest:                       # 没有冒号：整句当名字，试着从里面找数
        name, rest = raw, raw
    name = name.strip().lower()
    rest = rest.strip()
    out = {'name': name, 'value': None, 'value_max': None,
           'unit': '', 'cmp': '', 'raw': raw}

    rng = _RANGE_RE.search(rest)
    m = _PROP_RE.match(rest)
    if rng and (not m or rng.start() <= m.start(2)):
        out['value'] = _to_float(rng, 1)
        out['value_max'] = _to_float(rng, 5)
        tail = rest[rng.end():]
    elif m:
        c = (m.group(1) or '').strip().lower()
        out['cmp'] = _CMP_MAP.get(c, '')
        out['value'] = _to_float(m, 2)
        tail = rest[m.end():]
    else:
        return out
    out['unit'] = tidy_unit(tail)
    return out
