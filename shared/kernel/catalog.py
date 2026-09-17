# -*- coding: utf-8 -*-
"""shared.kernel.catalog —— 证据库目录：本地到底有哪些文献、每篇手上有什么。

**为什么需要它**（2026-09-13 用户拍板「Zotero 只是我个人取出来看的那一部分」）：
此前「这篇我有没有」这个问题全系统都是去问 Zotero（`zotero_client.library_index` /
`getpdf.doi_index`）。那等于说**库 = Zotero**。用户定的核心归属是反过来的：
    证据库（data/raw + data/curated）是全集，Zotero 是他自己挑出来读的子集。
所以「有没有」必须先问本地，Zotero 只是补充。这个文件就是「问本地」的唯一入口。

**真相是什么**：
    · `curated/<id>/meta.json`   —— 一篇一份的元数据（标题 / DOI / 年份 / 期刊 / 来源）
    · `raw/<id>/` 里实际躺着的文件 —— main.pdf、si.*、parsed/full.md …
本模块**不另建索引文件**：几百到几千个小 JSON 现扫是毫秒级的，
一个「可能跟文件不同步」的索引带来的 bug 比它省的时间贵得多（同 paperdb 的判据）。
但**进程内**可以缓存（2026-09-16 加，踩坑 #161）：`by_doi()` 一次扫 1000 个文件约半秒，
盯新刊 / 回填一天要问它几千次。缓存以两层目录的 mtime 为印章 —— 别的进程落了新文献
（新建目录）印章就变；本进程 `register()` 直接清缓存。meta.json 被别的进程改 DOI 这种事
不在印章里，但 DOI 落地后不会再变。

**只依赖 paths**（kernel 不依赖任何人）：不联网、不问 Zotero。
Zotero 那一半在 `shared.adapters.zotero_client`，两边靠 DOI 对账，由调用方合并。

用法：
    from shared.kernel import catalog
    catalog.find('10.1021/acs.macromol.5b00210')   # → 'doi_10.1021-acs.macromol.5b00210' 或 ''
    catalog.register(pid, doi=..., title=..., year=..., journal=..., source='fetch')
    titles, dois = catalog.have_index()             # 跟 zotero_client.library_index 同形状
    for r in catalog.scan(): ...                     # 每篇一条：手上有什么一目了然
"""
import io
import json
import os
import re
import time

from shared.kernel import paths

# meta.json 里本模块认得的字段。**只补不覆盖**是 register 的默认行为 ——
# 用户可能手工改过标题；精读流水线写的 model/time 也不该被落地这一步冲掉。
FIELDS = ('doi', 'title', 'year', 'journal', 'authors', 'source', 'landed_at',
          'zotero_key')

# 来源：这篇是怎么进证据库的。给人看、也给「回流 Zotero」那一步判断用。
SRC_FETCH = 'fetch'          # 借浏览器向出版商取的
SRC_ZOTERO = 'zotero'        # 从用户 Zotero 的附件复制过来的
SRC_LOCAL = 'local'          # 用户手上的文件直接给的
SRC_WECHAT = 'wechat'        # 公众号精读导入


def norm_doi(doi):
    """DOI 归一：去 URL 前缀、小写、去空白。对账全靠它，两边必须用同一个函数。"""
    d = (doi or '').strip()
    d = re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:)', '', d, flags=re.I)
    return d.strip().lower()


def norm_title(title):
    """标题归一（只留字母数字）—— 跟 zotero_client.library_index 同一种归法。"""
    return re.sub(r'[^a-z0-9]', '', (title or '').lower())


def read_meta(pid):
    """读一篇的 meta.json → dict；没有或坏了返回 {}。**不抛异常**。"""
    p = paths.meta(pid)
    if not os.path.isfile(p):
        return {}
    try:
        d = json.load(io.open(p, encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def doi_of(meta):
    """从 meta 里取 DOI。老数据（精读写的）用大写 `DOI` 键，新数据用小写 —— 两种都认。"""
    return norm_doi(meta.get('doi') or meta.get('DOI') or '')


def year_of(meta):
    """年份：有 `year` 用 `year`，否则从 `date`（如 '2025-11'）取前四位。"""
    y = meta.get('year')
    if y:
        try:
            return int(str(y)[:4])
        except ValueError:
            pass
    m = re.match(r'(\d{4})', str(meta.get('date') or ''))
    return int(m.group(1)) if m else None


def register(pid, overwrite=False, **fields):
    """把一篇登记进证据库（写 / 补 meta.json）→ 写完后的 meta。

    默认**只补不覆盖**：已有非空值一律保留，只填空缺的。
    `overwrite=True` 时给的值以我为准（用户明确要改时才用）。
    `doi` 会归一并同时写进老的大写 `DOI` 键，老读者不用改。
    没给 `landed_at` 就记现在。
    """
    pid = paths.check_key(pid)
    meta = read_meta(pid)
    before = dict(meta)
    if 'doi' in fields:
        fields['doi'] = norm_doi(fields['doi'])
    fields.setdefault('landed_at', time.strftime('%Y-%m-%d %H:%M'))
    for k, v in fields.items():
        if v in (None, '', [], {}):
            continue
        if overwrite or not meta.get(k):
            meta[k] = v
    if meta.get('doi') and not meta.get('DOI'):
        meta['DOI'] = meta['doi']
    meta.setdefault('key', pid)
    if meta == before:
        return meta                        # 没变化就不写盘：每小时回流会对全库登记一遍
    os.makedirs(paths.paper_dir(pid), exist_ok=True)
    io.open(paths.meta(pid), 'w', encoding='utf-8').write(
        json.dumps(meta, ensure_ascii=False, indent=1))
    _cache_clear()
    return meta


# SI 的三种状态（2026-09-17）。以前只有「盘上有没有」一个布尔，分不清「没取过」和「取过、出版商说没有」——
# 于是综述、老文献这种本来就没 SI 的，每次进「该补 SI」的清单都会再敲一次出版商。
SI_HAVE, SI_NONE, SI_UNKNOWN = 'have', 'none', 'unknown'


def si_status(pid):
    """这篇的 SI：have 盘上有 / none 取过、确认出版商没挂 / unknown 没取过或上次没取成。"""
    if paths.find_local_si(pid):
        return SI_HAVE
    return read_meta(pid).get('si_status') or SI_UNKNOWN


def mark_si_none(pid, why=''):
    """记下「这篇没有 SI」（出版商页面确认过），以后别再去取。"""
    register(pid, overwrite=True, si_status=SI_NONE, si_note=why or '出版商页面没挂补充材料')


def ids():
    """证据库里所有文献 id（curated 与 raw 两层目录名的并集，只认合法 id）。"""
    out = set()
    for layer in (paths.CURATED, paths.RAW):
        if not os.path.isdir(layer):
            continue
        for name in os.listdir(layer):
            if name.startswith(('_', '.')):
                continue                       # _incoming 之类的临时区不是文献
            try:
                out.add(paths.check_key(name))
            except paths.BadKeyError:
                continue
    return sorted(out)


def record(pid):
    """一篇的目录卡：元数据 + 手上有什么（都是布尔或路径，不读大文件）。"""
    pid = paths.check_key(pid)
    meta = read_meta(pid)
    si = paths.find_local_si(pid)
    return {
        'id': pid,
        'doi': doi_of(meta),
        'title': meta.get('title') or '',
        'year': year_of(meta),
        'journal': meta.get('journal') or meta.get('publicationTitle') or '',
        'source': meta.get('source') or '',
        'zotero_key': meta.get('zotero_key') or (pid if paths.is_zotero_key(pid) else ''),
        'in_zotero': bool(meta.get('zotero_key')) or paths.is_zotero_key(pid),
        'pdf': os.path.isfile(paths.local_pdf(pid)),
        'si': bool(si),
        'fulltext': os.path.isfile(paths.fulltext(pid)),
        'si_fulltext': os.path.isfile(paths.si_fulltext(pid)),
        'summary': os.path.isfile(paths.summary(pid)),
        'structured': os.path.isfile(paths.structured(pid)),
    }


def level_of(rec):
    """这篇在四级里到哪一级（2026-09-16 用户定的分级）：
    0 只有登记 / 1 有正文文本（解析过） / 2 有原件 PDF / 3 有精读。
    级别是**从手上有什么推出来的**，不另存字段 —— 文件在就是在，不会跟索引对不上。
    雷达库里那些（只有题目摘要）不在证据库，是 0 级；证据库里只登记没正本的也算 0。
    """
    if rec.get('summary'):
        return 3
    if rec.get('pdf'):
        return 2
    if rec.get('fulltext'):
        return 1
    return 0


def scan():
    """全库目录卡列表。几百篇是毫秒级；每次现扫，不缓存（理由见模块说明）。"""
    return [record(p) for p in ids()]


_CACHE = {'stamp': None, 'by_doi': None}


def _stamp():
    """两层目录的印章：有目录增删就变。取不到（目录还没建）返回 None = 不缓存。"""
    try:
        return tuple(os.stat(d).st_mtime_ns for d in (paths.CURATED, paths.RAW))
    except OSError:
        return None


def _cache_clear():
    _CACHE['stamp'] = None
    _CACHE['by_doi'] = None


def by_doi():
    """DOI → id。同一个 DOI 出现在两个目录下时**优先 Zotero 编号**（老数据在那边）。进程内缓存，见模块说明。"""
    st = _stamp()
    if st is not None and _CACHE['stamp'] == st and _CACHE['by_doi'] is not None:
        return dict(_CACHE['by_doi'])
    out = _scan_by_doi()
    if st is not None:
        _CACHE['stamp'], _CACHE['by_doi'] = st, dict(out)
    return out


def _scan_by_doi():
    out = {}
    for pid in ids():
        d = doi_of(read_meta(pid))
        if not d:
            continue
        if d not in out or (paths.is_zotero_key(pid) and not paths.is_zotero_key(out[d])):
            out[d] = pid
    return out


def find(doi):
    """这个 DOI 在证据库里吗 → id 或 ''。"""
    d = norm_doi(doi)
    if not d:
        return ''
    return by_doi().get(d, '')


def have_index():
    """(归一标题集合, DOI 集合) —— 与 `zotero_client.library_index()` 同形状，
    调用方把两者并起来就是「我有没有」的完整答案。"""
    titles, dois = set(), set()
    for pid in ids():
        meta = read_meta(pid)
        t = norm_title(meta.get('title'))
        if t:
            titles.add(t)
        d = doi_of(meta)
        if d:
            dois.add(d)
    return titles, dois


def search(text, limit=25):
    """按标题 / DOI / 期刊 子串搜（不分大小写）→ 目录卡列表。免费、秒回、不联网。"""
    q = (text or '').strip().lower()
    if not q:
        return []
    out = []
    for r in scan():
        hay = ' '.join([r['title'], r['doi'], r['journal'], r['id']]).lower()
        if q in hay:
            out.append(r)
            if len(out) >= limit:
                break
    return out


def stats():
    """证据库有多大、每种产物各几篇。"""
    rows = scan()
    keys = ('pdf', 'si', 'fulltext', 'si_fulltext', 'summary', 'structured', 'in_zotero')
    out = {'papers': len(rows), 'with_doi': sum(1 for r in rows if r['doi'])}
    for k in keys:
        out[k] = sum(1 for r in rows if r[k])
    return out
