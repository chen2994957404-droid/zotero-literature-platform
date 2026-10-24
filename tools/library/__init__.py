# -*- coding: utf-8 -*-
"""library · 查证据库：有没有这篇、库内检索、骨架与按节读原文、参考文献、检索 / 团队 / 专题。

**全部只读、全部免费。** agent 可以随便调、不用问人的工具包 —— 别的工具要么花钱要么改数据。

综合回答、比数值、读曲线不在这里 —— 那些交给 Claude Science（2026-10-23 起问答 / 数值库已删）。

**对外契约**（`cli.py` / `mcp.py` 只许调这些）：

| 入口 | 干什么 |
|---|---|
| `db_stats()` / `db_search(text)` / `db_have(doi)` | 证据库有多大 / 按标题 DOI 期刊搜 / 有没有这篇 |
| `retrieve(query, n, where)`  | 库内向量检索，返回段落与它在骨架里的地址 |
| `refs(key)`                  | 参考文献条目，标出库里已有的 |
| `outline(key)`               | **骨架菜单**：每节的地址/类别/字数/数字密度（缓存，免费）|
| `section(key, sec_id, si=)`  | **按地址取一节原文** —— 模型点菜的那一口 |
| `render_*`                   | 渲染成人/模型可读的 markdown |
另有子模块：`dbsearch`（检索：DOI / 标题词 / 作者 / 通讯 / 团队…）、`teams`（研究团队）、`oaindex`（作者摘要索引）、`census`（盘点）。

2026-10-13 Zotero 移出平台：原来这里一半是查 Zotero（stats / search / item / pdf / fulltext / 合集 / 标签 / 最近），
全删了，旧代码在 git 标签 `zotero-before-removal`。
"""
import io
import json
import os
import re
import sys

from shared.kernel import catalog, paths

MAX_CHARS = 20000          # 取全文的默认上限（再多模型也读不完，还占上下文）


# ══════════════════════════════════════════════════════════════════════
# 查
# ══════════════════════════════════════════════════════════════════════

# ── 证据库（全集）──────────────────────────────────────────────────────
# 证据库（data/raw + curated）是唯一的库。「我有没有这篇」问这里（零网络、秒回）。

def db_stats():
    """证据库有多大、每种产物各几篇（正本 / SI / 解析）。"""
    return catalog.stats()


def db_search(text, limit=25):
    """按标题 / DOI / 期刊 子串搜证据库 → 目录卡列表。不联网。"""
    return catalog.search(text, limit=limit)


def db_have(doi):
    """这个 DOI 在证据库里吗 → id 或 ''。"""
    return catalog.find(doi)


# ── 库内检索：给模型原料，不替它判断 ──────────────────────────────────
# 2026-09-14 加。此前模型想在证据库里「找哪里讲了 X」只有 `ask`（花钱调大模型写中文回答）。
# 模型要的其实是原料：哪几篇、哪一节、那段原文。这个函数零成本（本地向量化 + 本地库）。

def retrieve(query, n=8, where='all'):
    """向量检索证据库 → [{id, title, doi, source, sim, address, text}]。不过大模型、不花钱。

    `where`：'all' / 'main'（只正文）/ 'si'（只补充材料）。
    `address` 是这段在骨架里的地址（`s5.p3` 这种），拿去 `section()` 就能读上下文；
    定位不到时为空串（老的粗层块、或解析文本经过清洗对不上）。
    """
    from shared.adapters import vectordb
    from shared.adapters.embed import embed as embed_batch
    flt = {'source': 'si'} if where == 'si' else ({'source': 'main'} if where == 'main' else None)
    try:
        coll = vectordb.open_store()
        hits = coll.query(embed_batch([query])[0], n=max(1, int(n)), where=flt)
    finally:
        vectordb.close_all()          # 常驻的 MCP 进程别抱着连接（踩坑 #157）
    out = []
    for h in hits:
        m = h.get('meta') or {}
        key = m.get('key') or ''
        is_si = m.get('source') == 'si'
        out.append({'id': key, 'title': m.get('title') or '', 'doi': m.get('doi') or '',
                    'source': 'si' if is_si else 'main', 'sim': round(h.get('sim') or 0, 3),
                    'address': _locate(key, h.get('doc') or '', is_si) if key else '',
                    'text': h.get('doc') or ''})
    return out


def _locate(key, doc, si=False):
    """一段向量库文本 → 它在骨架里的地址（节 / 段）。找不到返回 ''。"""
    from shared.domain import outline as _outline
    from shared.domain.outline import scan
    try:
        o = outline(key)
    except Exception:
        return ''
    if not o.get('available'):
        return ''
    src = (o.get('si') or {}) if si else o
    path = paths.si_fulltext(key) if si else paths.fulltext(key)
    if not os.path.exists(path):
        return ''
    text = scan.clean_body(io.open(path, encoding='utf-8').read())
    needle = next((ln.strip() for ln in doc.splitlines() if len(ln.strip()) >= 40), '')
    pos = text.find(needle[:60]) if needle else -1
    if pos < 0:
        return ''
    for s in src.get('sections') or []:
        if s['start'] <= pos < s['end']:
            for p in s.get('paras') or []:
                if p['start'] <= pos < p['end']:
                    return p['id']
            return s['id']
    return ''


def render_retrieve(rows, query=''):
    """检索结果 → 给模型看的文本：每条带地址，读上下文用 library_section。"""
    if not rows:
        return '证据库里没有跟「%s」相近的段落。' % query
    out = ['跟「%s」最相近的 %d 段（按相似度）：' % (query, len(rows))]
    for i, r in enumerate(rows, 1):
        where = 'SI' if r['source'] == 'si' else '正文'
        addr = r['address'] or '?'
        out.append('%d. [%.3f] %s · %s %s · 《%s》' % (
            i, r['sim'], r['id'], where, addr, r['title'][:60]))
        out.append('   ' + r['text'][:400].replace('\n', ' ') + ('…' if len(r['text']) > 400 else ''))
    out.append('（要看上下文：library_section itemKey=<id> sectionId=<地址>，SI 的加 si=true）')
    return '\n'.join(out)


# ── 参考文献：让模型在证据库内部顺着引用走 ───────────────────────────

_REF_NUM = re.compile(r'^\s*(?:\(\d{1,3}\)|\[\d{1,3}\]|\d{1,3}\.)\s')   # 参考文献条目的编号：(12) / [12] / 12.


def refs(key):
    """这篇的参考文献条目 → [{n, text, doi, in_db, id}]。纯脚本，从解析出的全文里抽。

    `in_db` = 那篇已经在证据库里（按 DOI 对账；没 DOI 的按标题子串对）；`id` 是它的 id，
    直接拿去 `outline()` 就能读。模型读到 "[12]" 时用它知道 12 是谁、能不能立刻读。
    没有参考文献节返回空列表。
    """
    key = catalog.resolve(key)        # 旧的 Zotero 编号也认（2026-10-12 起目录改成 doi_ 编号）
    import re
    from shared.domain import outline as _outline
    from shared.domain.outline import scan
    o = outline(key)
    if not o.get('available'):
        return []
    md = io.open(paths.fulltext(key), encoding='utf-8').read()
    text = scan.clean_body(md)
    # 参考文献节不一定叫 References：Nature 式论文把它挂在「Received … accepted」下面。
    # 判据改成**内容**：哪一节里「(12) / [12] / 12. 」开头的条目最多，就是它（至少 5 条）。
    entry_re = re.compile(r'(?m)^\s*(?:\(\d{1,3}\)|\[\d{1,3}\]|\d{1,3}\.)\s+\S')
    best, best_n = None, 0
    for s in (o.get('sections') or []):
        n_ent = len(entry_re.findall(text[s['start']:s['end']]))
        if n_ent > best_n:
            best, best_n = s, n_ent
    if best is None or best_n < 5:
        return []
    sec = best
    body = text[sec['start']:sec['end']]
    body = '\n'.join(body.splitlines()[1:])           # 去掉标题行
    # 条目切分：`(12) ` / `[12] ` / `12. ` 开头；都没有就按空行
    parts = re.split(r'(?m)^\s*(?=\(\d{1,3}\)\s|\[\d{1,3}\]\s|\d{1,3}\.\s)', body)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) < 3:
        parts = [p.strip() for p in re.split(r'\n\s*\n', body) if p.strip()]
    # 关键词行不是参考文献（MineRU 常把 Keywords 挤进参考文献节开头；2026-09-30 复测：V2C7D8W4 的「第 1 条」
    # 其实是关键词行，编号 1 还因此出现两次）
    parts = [p for p in parts if not re.match(r'(?i)^\W*key\s*words?\b', p)]
    # 编号列表里没编号的那块不是参考文献（V2C7D8W4：关键词 + 「Received… Published online…」稿件日期
    # 粘成一块，带数字、不带 Keywords 字样，前两道都拦不住）
    numbered = [bool(_REF_NUM.match(p)) for p in parts]
    if parts and sum(numbered) >= 0.8 * len(parts):
        parts = [p for p, ok in zip(parts, numbered) if ok]
    by_doi = catalog.by_doi()
    # 标题子串对账只用**归一后**够长的标题：中文题名归一后是空串，'' in 任何字符串都成立，
    # 2026-09-14 实测一篇的 32 条参考文献全被标成「已在库」就是这么来的
    titles = {t: r['id'] for r in catalog.scan()
              for t in [catalog.norm_title(r['title'])] if len(t) >= 24}
    out = []
    for p in parts:
        m = re.match(r'^\s*(?:\((\d{1,3})\)|\[(\d{1,3})\]|(\d{1,3})\.)\s', p)
        n = int(next(g for g in (m.groups() if m else ()) if g)) if m else len(out) + 1
        doi = ''
        dm = re.search(r'10\.\d{4,9}/[^\s"<>\)\]]+', p)
        if dm:
            doi = catalog.norm_doi(dm.group(0).rstrip('.;,'))
        pid = by_doi.get(doi, '') if doi else ''
        if not pid:
            norm = catalog.norm_title(p)
            pid = next((v for t, v in titles.items() if t in norm), '')
        body_txt = p[m.end():] if m else p                 # 去掉条目自己的编号，别跟 [n] 重复显示
        if not re.search(r'\d', body_txt):
            # 参考文献一定带数字（年份、卷页）；一个数字都没有的是关键词行之类（2026-09-30：V2C7D8W4 的
            # 关键词行不带「Keywords」字样，33 条因此对不上 Crossref 的 32 条，DOI 也补不上）
            continue
        out.append({'n': n, 'text': re.sub(r'\s+', ' ', body_txt).strip()[:300], 'doi': doi,
                    'in_db': bool(pid), 'id': pid})
    return out


def render_refs(rows, key=''):
    if not rows:
        return '%s：没有找到参考文献节（可能还没解析，或这篇没有参考文献）。' % key
    have = sum(1 for r in rows if r['in_db'])
    out = ['%s 的参考文献 %d 条，其中 %d 条已在证据库里（标 ★，可直接 library_outline 读）：'
           % (key, len(rows), have)]
    for r in rows:
        out.append('%s[%d] %s%s' % ('★' if r['in_db'] else ' ', r['n'], r['text'][:150],
                                   ('  → ' + r['id']) if r['id'] else ''))
    return '\n'.join(out)


def render_db(rows):
    """目录卡 → 给人/模型看的文本：每篇一行，手上有什么用几个字标出来。"""
    if not rows:
        return '证据库里没有匹配的。'
    out = []
    for r in rows:
        have = ''.join(('正' if r['pdf'] else '·', 'S' if r['si'] else '·',
                        '析' if r['fulltext'] else '·'))
        out.append(f'{r["id"]:<38} [{have}] {r["year"] or "????"}  {r["title"][:70]}'
                   + (f'\n{"":<38} DOI:{r["doi"]}' if r['doi'] else ''))
    out.append('（[正S析] = 有正文 / 有SI / 已解析）')
    return '\n'.join(out)


def outline(key, refresh=False):
    """这篇的**骨架**：每节的地址、类别、字数、含多少数字/表/图。

    没有解析过的文献（没有 `parsed/full.md`）返回 `available=False` ——
    **不是错误**，是「这篇还没取到全文，要先解析」这个事实。

    结果缓存在 `curated/<key>/outline.json`：算一次几十毫秒，但一天要被点很多次。
    缓存带签名（`outline.signature`：文本 + 算法版本），对不上就重算。
    """
    key = catalog.resolve(key)        # 旧的 Zotero 编号也认（2026-10-12 起目录改成 doi_ 编号）
    from shared.domain import outline as _outline
    md_path = paths.fulltext(key)
    if not os.path.exists(md_path):
        return {'itemKey': key, 'available': False,
                'why': '这篇还没有解析出全文（parsed/full.md 不存在）'}
    cache = paths.outline(key)
    md = io.open(md_path, encoding='utf-8').read()
    si_path = paths.si_fulltext(key)
    si_md = io.open(si_path, encoding='utf-8').read() if os.path.exists(si_path) else ''
    # 新鲜度看**签名**（哪份文本 + 哪版算法），不看修改时间：清洗规则或骨架算法改了、
    # full.md 没动时，按时间判会一直用错位的旧缓存（2026-09-30，1034/1090 篇中招）
    if not refresh and os.path.exists(cache):
        try:
            d = json.load(io.open(cache, encoding='utf-8'))
            if _outline.is_current(d, md, si_md):
                d.update({'itemKey': key, 'available': True, 'cached': True})
                return d
        except Exception:
            pass                      # 缓存坏了就重算，不让它拖垮这次调用
    d = _outline.build_outline(md, si_md=si_md)
    try:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        json.dump(d, io.open(cache, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    except OSError:
        pass                          # 写不下缓存不影响这次的结果
    d.update({'itemKey': key, 'available': True, 'cached': False})
    return d


def section(key, sec_id, max_chars=MAX_CHARS, si=False):
    """按地址取这篇的一节原文。地址来自 `outline()` 里的 `id`（`s4` 这种）。

    **这是「点菜」的那一口**：模型看完菜单只取它要的两三节，
    而不是把 5 万字符的全文塞进上下文。
    """
    key = catalog.resolve(key)        # 旧的 Zotero 编号也认（2026-10-12 起目录改成 doi_ 编号）
    from shared.domain import outline as _outline
    o = outline(key)
    if not o.get('available'):
        return {'itemKey': key, 'id': sec_id, 'text': '', 'chars': 0,
                'why_empty': o.get('why', '')}
    path = paths.si_fulltext(key) if si else paths.fulltext(key)
    if not os.path.exists(path):
        return {'itemKey': key, 'id': sec_id, 'text': '', 'chars': 0,
                'why_empty': '这篇没有 SI 全文' if si else '没有正文全文'}
    md = io.open(path, encoding='utf-8').read()
    src = (o.get('si') or {}) if si else o
    text = _outline.section_text(md, src, sec_id)
    if not text:
        ids = _outline.addresses(src)
        return {'itemKey': key, 'id': sec_id, 'text': '', 'chars': 0,
                'why_empty': '没有这个地址；可用的有：%s' % ', '.join(ids[:30])}
    return {'itemKey': key, 'id': sec_id, 'text': text[:max_chars],
            'chars': min(len(text), max_chars),
            'truncated': len(text) > max_chars, 'why_empty': ''}


def render_outline(d):
    """骨架 → 给模型看的菜单文本（几百 token）。"""
    from shared.domain import outline as _outline
    if not d.get('available'):
        return '%s：%s' % (d.get('itemKey', ''), d.get('why', '没有骨架'))
    st = d.get('stats') or {}
    head = ('%s · 全文 %d 字符 · %d 节%s\n'
            '（按 id 点菜：library_section itemKey=%s sectionId=s4 —— '
            '长节可点到段 s4.p2，表 t1、图注 f2 也能单独取）\n'
            % (d.get('itemKey', ''), st.get('chars', 0), st.get('n_sections', 0),
               '· 有 SI' if d.get('si') else '', d.get('itemKey', '')))
    body = _outline.menu(d)
    si = d.get('si')
    if si:
        body += '\n--- 补充材料 SI ---\n' + _outline.menu(si)
    return head + body
