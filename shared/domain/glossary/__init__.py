# -*- coding: utf-8 -*-
"""glossary · 领域术语表：英文缩写/全称 → 中文译名。挖、洗、查、校验，全是纯逻辑。

**为什么有它**（2026-09-18）：本地模型精读时数字不会编（有回查），**名字会错** ——
PVDF 写成「聚丙烯腈」、mesitylhydroborate 译名胡来。小模型化学词汇薄，又没人给它查表。
命名是封闭世界，**查表能替代记忆**：这是「脚本补小模型知识短板」里唯一能做到位的一维。

**料从哪来**：用户认可的 774 篇公众号范文里「中文名（英文缩写）」的写法（2026-09-18 试挖 4885 对、2383 个词），
第二层可从 Wikidata 补缺（联网，住 adapters，不在这里）。

住 `shared/domain/`：不联网、不读盘、不知道文件在哪 —— 表由调用方传进来（dict）。
使用者：`tools/deepread`（注入提示词 + 生成后校验）、`tools/ask`（答案校验）。

| 函数 | 干什么 |
|---|---|
| `mine(texts)` | 从一批中文文本里挖「中文（英文）」对 → {en: {zh: 次数}} |
| `build(counts, min_count=2)` | 洗：去动词前缀、合并后缀变体、留可信译名 → 表 {en: {'zh': [主译名, 备选…], 'n': 次数}} |
| `lookup(table, term)` | 一个英文词/缩写 → 译名列表（没有就空） |
| `prompt_block(table, text)` | 这篇原文里出现过的缩写 → 塞进提示词的「译名（必须照用）」段 |
| `mismatches(table, output)` | 产出里「中文（缩写）」与表不符的 → [(缩写, 写成了, 应为)]；只对票≥5 且无歧义的词强制 |
"""
import re
from collections import Counter, defaultdict

# 「中文名（英文）」：中文 2–15 字（含数字与连字符），括号里 2–30 个英文字符
_PAIR = re.compile(r'([一-鿿][一-鿿\d\-]{1,14})[（(]([A-Za-z][A-Za-z0-9\-\',\. ]{1,30})[)）]')
# 粘在中文名前面的动词 / 虚词：「采用扫描电子显微镜」→「扫描电子显微镜」
_LEAD = re.compile(r'^(?:并|再|先|后|均|即|如|以及|以|用|采用|通过|利用|使用|借助|结合|运用|经|经由|基于|由|和|与|及|或|的|该|这|其|在|将|对|把|为|是|从|含|含有|包括|包含|引入|加入|添加|得到|制备|合成|测定|测试|表征|分析|观察|记录|进行|开展|完成|实验药品是|实验药品包括|主要实验药品是)+')
# 括号里像一个「缩写 / 名称」的：全大写缩写、带数字的代号、或英文全称；排除单个字母与纯数字
_TERM_OK = re.compile(r'^(?:[A-Z][A-Za-z0-9\-\']{1,}|[A-Za-z][a-z]+(?: [a-z\-]+){0,4})$')


def _clean_zh(zh):
    zh = _LEAD.sub('', zh)
    return zh if 2 <= len(zh) <= 15 else ''


def mine(texts):
    """一批中文文本 → {英文词: Counter(中文名)}。只挖不洗。"""
    counts = defaultdict(Counter)
    for t in texts:
        for zh, en in _PAIR.findall(t or ''):
            en = en.strip().rstrip('.')
            if not _TERM_OK.match(en):
                continue
            zh = _clean_zh(zh)
            if zh:
                counts[en][zh] += 1
    return counts


def build(counts, min_count=2, keep=3):
    """洗成表。规则：
    - 「扫描电子显微镜」是「采用扫描电子显微镜」的后缀 → 后者的票归前者（已在 _clean_zh 去了大半，这里兜底）
    - 一个英文词留最多 `keep` 个译名，按票数排；票数 < min_count 的不要（一次性的多半是错的或含上下文）
    - 歧义（TA = 单宁酸 / 硫辛酸）就都留着，主译名是票最多的
    """
    table = {}
    for en, c in counts.items():
        merged = Counter()
        names = sorted(c, key=len)
        for zh in names:
            owner = next((s for s in names if s != zh and len(s) < len(zh) and zh.endswith(s)), None)
            merged[owner or zh] += c[zh]
        good = [(zh, n) for zh, n in merged.most_common() if n >= min_count][:keep]
        if good:
            table[en] = {'zh': [zh for zh, _ in good], 'n': sum(n for _, n in good)}
    return table


def lookup(table, term):
    e = (table or {}).get(term) or (table or {}).get((term or '').strip())
    return list(e['zh']) if e else []


_ABBR_IN_TEXT = re.compile(r'\b[A-Z][A-Za-z0-9\-]{1,12}\b')


def terms_in(table, text, limit=40):
    """原文里出现、表里也有的英文词（按出现次数排）。"""
    seen = Counter(m.group(0) for m in _ABBR_IN_TEXT.finditer(text or ''))
    hits = [(t, n) for t, n in seen.most_common() if t in (table or {})]
    return [t for t, _ in hits[:limit]]


def prompt_block(table, text, limit=40):
    """塞进提示词的一段：只列这篇原文里出现过的词，不塞整张表。"""
    ts = terms_in(table, text, limit)
    if not ts:
        return ''
    items = []
    for t in ts:
        zh = lookup(table, t)
        items.append('%s=%s' % (t, zh[0]) if len(zh) == 1 else '%s=%s（按原文全称定）' % (t, '/'.join(zh)))
    return '若要给中文名，公众号惯用的译名是（仅供参考，缩写本身保持缩写）：' + '；'.join(items)


# 只有「票数够多、且只有一个意思」的词才拿来纠错。2026-09-18 抽检抓到反例：表里 ODA=十八胺（octadecylamine），
# 而那篇的 ODA 是八亚甲基二胺（octamethylenediamine），论文没错、表错了；GF 在表里是玻璃纤维/应变系数，那篇是石墨烯泡沫。
# 缩写在不同论文里指不同东西是常态 —— 歧义词和票少的词只当提示塞进提示词，**不强制**。
ENFORCE_MIN = 5


def enforceable(table, term):
    e = (table or {}).get(term)
    return bool(e) and len(e['zh']) == 1 and e.get('n', 0) >= ENFORCE_MIN


def mismatches(table, output):
    """产出里写成「中文（缩写）」的，缩写在表里（且可强制）、中文却不在表里的 → [(缩写, 写成了, 应为)]。

    只判「中文名 + 括号缩写」这种明确对应的写法；单独出现的缩写不判（无法知道它想说哪个词）。
    """
    out, seen = [], set()
    for zh, en in _PAIR.findall(output or ''):
        en = en.strip()
        accepted = lookup(table, en)
        if not accepted or en in seen or not enforceable(table, en):
            continue
        zh = _clean_zh(zh) or zh
        if not any(zh.endswith(a) or a.endswith(zh) for a in accepted):
            seen.add(en)
            out.append((en, zh, accepted[0]))
    return out
