# -*- coding: utf-8 -*-
"""journals · 期刊分级：这篇发在什么刊上，那本刊有多重。

**为什么要有**（用户 2026-09-05 提出，09-07 做）：用户的原话是
「不看不引 MDPI 等低可信度开放获取刊」。可库里 188 篇里哪些是这类刊，
此前**没有任何一处记着** —— 每次都要人去认刊名。分级之后，
「这条数据有多可信」终于有了两条腿：数字本身能不能追溯（`located`），
以及它出自什么刊。

**指标从哪来**：OpenAlex 的 `/sources` 端点（免费、无需密钥）——
`summary_stats.2yr_mean_citedness` 就是影响因子那个口径，
另有 `h_index`、是不是开放获取、在不在 DOAJ、出版商是谁。
中科院分区与 JCR 都要订阅才拿得到，SCImago 的下载口有 Cloudflare 挡着
（2026-09-07 实测 curl 拿回来的是验证页），所以现成的免费源只有这一个。

**分级不是排名**，是「读它之前该带多少警惕」：

| 档 | 判据（近两年篇均被引） | 怎么用 |
|---|---|---|
| `顶刊` | >= 15 | 结论可以当行业共识看 |
| `一流` | >= 8 | 正常引用 |
| `常规` | >= 3 | 正常引用，数字最好回原文核 |
| `一般` | < 3 或查不到 | 当线索，不当证据 |
| `慎用` | 命中用户自己的名单 | **用户明确说过不看不引** |

**用户的名单永远压过指标**：`data/serving/journal_overrides.json` 里写了什么就是什么 ——
那是他的领域判断，不是我们能算出来的。文件不存在时用内置默认
（**只含他说过的那一条**，别替他扩充：写多了就是拿我的偏见冒充他的）。

真相是 `data/serving/journals.json`，`tools/paperdb` 只读它。
"""
import io
import json
import os
import sys
import time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters import openalex
from shared.kernel import paths
from shared.kernel.cli import flag, opt
from shared.kernel.log import get_logger

log = get_logger('curate.journals')

TIERS = ('顶刊', '一流', '常规', '一般', '慎用')

DEFAULT_OVERRIDES = {
    'publishers': {'Multidisciplinary Digital Publishing Institute': '慎用'},
    'journals': {},
    'note': '用户 2026-09-05：不看不引 MDPI 等低可信度开放获取刊。'
            '想改就直接编辑本文件：publishers 按出版商、journals 按刊名'
            '（都用 OpenAlex 里的写法，大小写不敏感、按包含匹配）。',
}


def overrides_path():
    """用户自己的名单在哪。"""
    return os.path.join(paths.SERVING, 'journal_overrides.json')


def load_overrides():
    """读用户名单；没有就写一份内置默认出去 —— 让他看得见、改得动。"""
    p = overrides_path()
    if os.path.exists(p):
        try:
            d = json.load(io.open(p, encoding='utf-8'))
            if isinstance(d, dict):
                return d
        except Exception:
            log.warning('%s 读不出来，先用内置默认', p)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(DEFAULT_OVERRIDES, io.open(p, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    return DEFAULT_OVERRIDES


def tier_of(source, overrides=None):
    """一本刊 → (档次, 为什么)。**纯函数**：给什么算什么，不联网不读盘。"""
    ov = overrides or {}
    name = ((source or {}).get('display_name') or '').lower()
    pub = ((source or {}).get('host_organization_name') or '').lower()
    for hay, table, who in ((name, ov.get('journals') or {}, '刊名'),
                            (pub, ov.get('publishers') or {}, '出版商')):
        for k, v in table.items():
            if k and str(k).lower() in hay:
                return v, '%s命中用户名单（%s）' % (who, k)
    st = (source or {}).get('summary_stats') or {}
    c2 = st.get('2yr_mean_citedness')
    if c2 is None:
        return '一般', '查不到刊级指标'
    c2 = float(c2)
    for cut, tier in ((15, '顶刊'), (8, '一流'), (3, '常规')):
        if c2 >= cut:
            return tier, '近两年篇均被引 %.1f' % c2
    return '一般', '近两年篇均被引 %.1f' % c2


def _dois_by_key(keys=None):
    """{key: doi}。刊名不在任何本地文件里（只有 DOI），所以得走 OpenAlex 反查。

    **DOI 有两个来源，都要看**（2026-09-07 实测补的）：
      · `curated/<key>/meta.json` —— 精读线产出的，只有精读过的篇才有
      · `structured/<key>.json` 与 `abstracts/<Wxxx>.json` —— 抽取产出的，覆盖广得多

    只看前者时，188 篇的库里只有 51 篇查得到刊 —— 粗层那些篇（从 Zotero 全文索引抽的）
    压根没有 meta.json。而它们的 DOI 明明就在结构化记录里躺着。
    """
    out = {}
    for key in (keys or paths.all_keys()):
        p = paths.meta(key)
        if not os.path.exists(p):
            continue
        try:
            d = json.load(io.open(p, encoding='utf-8'))
        except Exception:
            continue
        doi = (d.get('DOI') or '').strip()
        if doi:
            out[key] = doi
    if keys:
        return out
    for folder in (paths.STRUCTURED, paths.ABSTRACTS):
        if not os.path.isdir(folder):
            continue
        for f in sorted(os.listdir(folder)):
            if not f.endswith('.json'):
                continue
            try:
                d = json.load(io.open(os.path.join(folder, f), encoding='utf-8'))
            except Exception:
                continue
            k, doi = d.get('key'), (d.get('doi') or '').strip()
            if k and doi and k not in out:
                out[k] = doi
    return out


def refresh(keys=None, log_fn=print):
    """全库刷一遍期刊分级 -> `data/serving/journals.json`。**免费**（只走 OpenAlex）。

    两步：DOI -> 发在哪本刊（works 端点）；刊 -> 刊级指标（sources 端点）。
    查不到刊的篇如实计进 `no_journal`，不假装覆盖了全库。
    """
    ov = load_overrides()
    dois = _dois_by_key(keys)
    log_fn('有 DOI 的 %d 篇，去 OpenAlex 查它们发在哪…' % len(dois))
    works = openalex.works_by_dois(list(dois.values()), allow_partial=True)
    by_doi = {}
    for w in works.values():
        doi = (w.get('doi') or '').replace('https://doi.org/', '').lower()
        src = ((w.get('primary_location') or {}).get('source')) or {}
        if doi and src:
            by_doi[doi] = src
    issns = set(s.get('issn_l') for s in by_doi.values() if s.get('issn_l'))
    log_fn('涉及 %d 本刊，取刊级指标…' % len(issns))
    sources = openalex.sources_by_issn(issns)

    journals, by_key, missing = {}, {}, 0
    for key, doi in dois.items():
        src = by_doi.get(doi.lower())
        issn = (src or {}).get('issn_l')
        if not issn:
            missing += 1
            continue
        by_key[key] = issn
        if issn in journals:
            continue
        full = sources.get(issn) or src
        st = full.get('summary_stats') or {}
        tier, why = tier_of(full, ov)
        journals[issn] = {
            'name': full.get('display_name') or src.get('display_name'),
            'publisher': full.get('host_organization_name') or '',
            'is_oa': bool(full.get('is_oa')),
            'in_doaj': bool(full.get('is_in_doaj')),
            'cite2yr': st.get('2yr_mean_citedness'),
            'h_index': st.get('h_index'),
            'works_count': full.get('works_count'),
            'tier': tier, 'why': why,
        }
    out = {'journals': journals, 'by_key': by_key,
           'built_at': time.strftime('%Y-%m-%d %H:%M:%S'),
           'no_journal': missing}
    p = paths.journals()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(out, io.open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    counts = {}
    for j in journals.values():
        counts[j['tier']] = counts.get(j['tier'], 0) + 1
    log_fn('%d 篇 -> %d 本刊：' % (len(by_key), len(journals))
           + '、'.join('%s %d' % (t, counts.get(t, 0)) for t in TIERS)
           + ('；%d 篇查不到刊' % missing if missing else ''))
    log_fn('写出：%s' % p)
    log_fn('用户名单：%s（想改哪本刊直接编辑它，再跑一次）' % overrides_path())
    return out


def load():
    """读回分级结果；没有就返回空结构（调用方不必判断文件在不在）。"""
    p = paths.journals()
    if not os.path.exists(p):
        return {'journals': {}, 'by_key': {}}
    try:
        d = json.load(io.open(p, encoding='utf-8'))
        return d if isinstance(d, dict) else {'journals': {}, 'by_key': {}}
    except Exception:
        return {'journals': {}, 'by_key': {}}


def main():
    """命令行：`python -m tools.curate journals`（只读外网、不写 Zotero、不花钱）。"""
    if flag('--list'):
        d = load()
        rank = dict((t, i) for i, t in enumerate(TIERS))
        for issn, j in sorted(d.get('journals', {}).items(),
                              key=lambda kv: (rank.get(kv[1]['tier'], 9),
                                              kv[1]['name'] or '')):
            print('%-5s %-10s %-44s %s' % (j['tier'], issn,
                                           (j['name'] or '')[:42], j['why']))
        print('共 %d 本刊，覆盖 %d 篇' % (len(d.get('journals', {})),
                                          len(d.get('by_key', {}))))
        return
    refresh(keys=[opt('--key')] if opt('--key') else None)


if __name__ == '__main__':
    main()
