# -*- coding: utf-8 -*-
"""library · 查我的 Zotero 库：搜条目、看合集标签、拿正文 PDF 与全文。

**全部只读、全部免费、全部不写任何东西。** 这是整个平台里唯一一个
agent 可以随便调、不用问人的工具包 —— 别的工具要么花钱要么改数据。

与另外两个「查库」的分工（选错工具是模型最常犯的错，SKILL.md 里也写了）：

    library  → 查 **Zotero 原始条目**：标题/作者/标签/合集/PDF/全文索引。免费、秒回
    ask      → **问**我的库，大模型读向量库后中文作答并附来源。花钱
    paperdb  → 查 **抽取出来的结构化数值**（拉伸强度 > 10 MPa 这种）。免费

**对外契约**（`cli.py` / `mcp.py` 只许调这些）：

| 入口 | 干什么 |
|---|---|
| `stats()`                    | 库统计 + Zotero 本地 API 通不通 |
| `search(...)`                | 按词/标签/类型/合集搜顶层条目 |
| `item(key)`                  | 单篇完整信息（元数据 + 附件 + 笔记数 + 正文 PDF）|
| `pdf(key)`                   | 定位正文 PDF 本地路径（自动排除 SI）|
| `fulltext(key, max_chars)`   | 取正文全文文本（Zotero 全文索引）|
| `outline(key)`               | **骨架菜单**：每节的地址/类别/字数/数字密度（缓存，免费）|
| `section(key, sec_id, si=)`  | **按地址取一节原文** —— 模型点菜的那一口 |
| `collections()`              | 合集（含父子层级）|
| `collection_items(key, n)`   | 某个合集里的文献 |
| `tags()`                     | 全部标签及各自文献数 |
| `recent(days, limit)`        | 最近 N 天新增/修改 |
| `render_*`                   | 把上面的结果渲染成人/模型可读的 markdown |

**它组合了什么**：只有 `shared.adapters.zotero_client` 一块 ——
本工具包一行网络代码都没有，Zotero API 长什么样只有适配层知道。

R4 窗（2026-08-31）从 `host/mcp/zotero_server.py` 切出来。为什么单独成工具而不是
并进 `ask`：`ask` 花钱（要调大模型），按 R4 的判据只能暴露成 prompt（由人点）；
而这些查询免费只读，必须是 tool（模型可自己调）。塞进 ask 会让它们一起降级成
prompt —— DSH 上现有的 `mcp__zotero__*` 自动检索当场失效。**判据优先于映射表。**
"""
import io
import json
import os
import sys
from datetime import datetime, timezone

from shared.adapters import zotero_client as zc
from shared.kernel import catalog, paths

MAX_CHARS = 20000          # 取全文的默认上限（再多模型也读不完，还占上下文）
RECENT_SCAN = 100          # 「最近 N 天」先按修改时间倒序取这么多，再按天过滤


# ══════════════════════════════════════════════════════════════════════
# 查
# ══════════════════════════════════════════════════════════════════════

# ── 证据库（全集）──────────────────────────────────────────────────────
# 2026-09-13 起：证据库（data/raw + curated）是全集，Zotero 是用户挑出来读的子集。
# 「我有没有这篇」先问这里（零网络、秒回），Zotero 那一半在下面那组函数。

def db_stats():
    """证据库有多大、每种产物各几篇（正本 / SI / 解析 / 精读 / 结构化 / 在 Zotero）。"""
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
    from shared.domain.schema import outline as _outline, scan
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

def refs(key):
    """这篇的参考文献条目 → [{n, text, doi, in_db, id}]。纯脚本，从解析出的全文里抽。

    `in_db` = 那篇已经在证据库里（按 DOI 对账；没 DOI 的按标题子串对）；`id` 是它的 id，
    直接拿去 `outline()` 就能读。模型读到 "[12]" 时用它知道 12 是谁、能不能立刻读。
    没有参考文献节返回空列表。
    """
    import re
    from shared.domain.schema import outline as _outline, scan
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
                        '析' if r['fulltext'] else '·', '精' if r['summary'] else '·',
                        '构' if r['structured'] else '·'))
        z = ' [Zotero]' if r['in_zotero'] else ''
        out.append(f'{r["id"]:<38} [{have}] {r["year"] or "????"}  {r["title"][:70]}{z}'
                   + (f'\n{"":<38} DOI:{r["doi"]}' if r['doi'] else ''))
    out.append('（[正S析精构] = 有正文 / 有SI / 已解析 / 已精读 / 已结构化）')
    return '\n'.join(out)


# ── Zotero（用户的阅读桌）───────────────────────────────────────────────

def stats():
    """Zotero 统计 + 通不通。**不抛异常** —— Zotero 没开是常态，不是错误。"""
    top, cols, tags_ = zc.counts()
    reachable = any(v is not None for v in (top, cols, tags_))
    return {'zotero_reachable': reachable, 'top_items': top,
            'collections': cols, 'tags': tags_}


def search(query=None, qmode='titleCreatorYear', tag=None, item_type=None,
           collection=None, limit=25, start=0):
    """按词/标签/类型/合集搜顶层条目，返回压平后的条目列表。

    qmode 默认 `titleCreatorYear`（只搜标题作者年份，准）；
    传 `everything` 连全文一起搜，召回高得多但也更吵。
    """
    items = zc.search_items(query=query or '', limit=limit, qmode=qmode, tag=tag,
                            item_type=item_type, collection=collection, start=start)
    return [zc.simplify(i) for i in items]


def item(key):
    """单篇完整信息：元数据 + 附件清单 + 笔记数 + 正文 PDF 路径。"""
    simp = zc.simplify(zc.item(key))
    atts, notes = [], 0
    try:
        for c in zc.children(key):
            d = c.get('data', {})
            if d.get('itemType') == 'attachment':
                atts.append({'key': c['key'], 'title': d.get('title'),
                             'contentType': d.get('contentType')})
            elif d.get('itemType') == 'note':
                notes += 1
    except Exception:
        pass          # 子条目取不到不阻塞主结果（Zotero 同步中偶尔会这样）
    pdf_path, pdf_att = zc.find_pdf(key, return_att_key=True)
    return {'item': simp, 'attachments': atts, 'notes_count': notes,
            'pdf_path': pdf_path, 'pdf_attachment_key': pdf_att}


def pdf(key):
    """定位正文 PDF 本地路径（排除 SI）。没有就 pdf_path=None，不算错误。"""
    p, att = zc.find_pdf(key, return_att_key=True)
    return {'itemKey': key, 'pdf_path': p, 'attachment_key': att}


def fulltext(key, max_chars=MAX_CHARS):
    """取正文全文文本（Zotero 自带全文索引，不解析 PDF —— 免费、瞬时）。

    取不到全文有两种常见原因，都不是 bug：没建索引、或扫描件没有文本层。
    要真正的版面解析走 `tools.deepread`（那要花钱）。
    """
    _, att = zc.find_pdf(key, return_att_key=True)
    if not att:
        return {'itemKey': key, 'text': '', 'chars': 0, 'truncated': False,
                'why_empty': '没有正文 PDF 附件'}
    text = zc.get_fulltext(att) or ''
    if not text:
        return {'itemKey': key, 'text': '', 'chars': 0, 'truncated': False,
                'why_empty': 'Zotero 全文索引为空（未建索引，或扫描件无文本层）'}
    truncated = len(text) > max_chars
    return {'itemKey': key, 'text': text[:max_chars], 'chars': min(len(text), max_chars),
            'truncated': truncated, 'why_empty': ''}


def units(key, type_=None, limit=200):
    """这篇的**单元库**（2026-09-22）：拆出来的最小信息单元（数值事实 / 实体 / 主张…），每条带原文引用与生产者。

    抽取 / 精读 / 审稿都往里写，这里只读。`type_` 限定一类；没有文件返回空。
    """
    from shared.kernel import units_store
    rows = units_store.load(key)
    if type_:
        rows = [u for u in rows if u.get('type') == type_]
    return {'key': key, 'stats': units_store.stats(units_store.load(key)), 'units': rows[:limit], 'total': len(rows)}


def render_units(d):
    L = ['%s 的单元库：%s（共 %d 条）' % (d['key'], d['stats'] or '空', d['total'])]
    for u in d['units']:
        f = u.get('fields') or {}
        body = ' · '.join('%s=%s' % (k, v) for k, v in f.items() if v)
        L.append('- [%s] %s  ←「%s」' % (u['type'], body[:120], (u.get('src') or {}).get('quote', '')[:60]))
    return '\n'.join(L)


def outline(key, refresh=False):
    """这篇的**骨架**：每节的地址、类别、字数、含多少数字/表/图。

    没有解析过的文献（没有 `parsed/full.md`）返回 `available=False` ——
    **不是错误**，是「这篇还没取到全文，要先解析」这个事实。

    结果缓存在 `curated/<key>/outline.json`：算一次几十毫秒，但一天要被点很多次。
    `full.md` 比缓存新时自动重算（跟 paperdb 的新鲜度判据同一个道理）。
    """
    from shared.domain.schema import outline as _outline
    md_path = paths.fulltext(key)
    if not os.path.exists(md_path):
        return {'itemKey': key, 'available': False,
                'why': '这篇还没有解析出全文（parsed/full.md 不存在）'}
    cache = paths.outline(key)
    if not refresh and os.path.exists(cache) and (
            os.path.getmtime(cache) >= os.path.getmtime(md_path)):
        try:
            d = json.load(io.open(cache, encoding='utf-8'))
            d.update({'itemKey': key, 'available': True, 'cached': True})
            return d
        except Exception:
            pass                      # 缓存坏了就重算，不让它拖垮这次调用
    md = io.open(md_path, encoding='utf-8').read()
    si_path = paths.si_fulltext(key)
    si_md = io.open(si_path, encoding='utf-8').read() if os.path.exists(si_path) else ''
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
    from shared.domain.schema import outline as _outline
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
    from shared.domain.schema import outline as _outline
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


def collections():
    """全部合集，压平成 [{key, name, parent}]（层级由 render 拼）。"""
    out = []
    for c in zc.collections():
        d = c.get('data', {})
        out.append({'key': c['key'], 'name': d.get('name'),
                    'parent': d.get('parentCollection') or None})
    return out


def collection_items(collection_key, limit=25):
    """某个合集里的顶层文献。"""
    return [zc.simplify(i) for i in zc.collection_items(collection_key, limit=limit)]


def tags():
    """全部标签及各自文献数，按文献数降序。"""
    rows = [{'tag': t.get('tag'), 'numItems': t.get('meta', {}).get('numItems') or 0}
            for t in zc.tags()]
    rows.sort(key=lambda r: r['numItems'], reverse=True)
    return rows


def recent(days=7, limit=25):
    """最近 N 天内新增/修改的文献。"""
    items = zc.recent_items(limit=RECENT_SCAN)
    keep = [i for i in items if _within(i.get('data', {}).get('dateModified'), days)]
    return [zc.simplify(i) for i in keep[:limit]]


def _within(iso, days):
    """这个 ISO 时间戳在最近 days 天内吗？解析不了的保守保留（宁可多给不漏给）。"""
    try:
        dt = datetime.fromisoformat((iso or '').replace('Z', '+00:00'))
    except Exception:
        return True
    return (datetime.now(timezone.utc) - dt).total_seconds() <= days * 86400


# ══════════════════════════════════════════════════════════════════════
# 渲染（纯字符串，不联网，可离线自测）
# ══════════════════════════════════════════════════════════════════════

def render_items(items, total=None):
    """条目列表 → markdown。"""
    if not items:
        return '（无结果）'
    lines = []
    if total is not None:
        lines += [f'共 {total} 条，显示前 {len(items)} 条：', '']
    for it in items:
        head = f"### {it.get('title') or '(无标题)'}"
        if it.get('date'):
            head += f"（{it['date']}）"
        lines.append(head)
        meta = []
        if it.get('creators'):
            meta.append('; '.join(it['creators'][:6]))
        if it.get('publicationTitle'):
            meta.append(it['publicationTitle'])
        if it.get('itemType'):
            meta.append(it['itemType'])
        if meta:
            lines.append('> ' + ' · '.join(meta))
        if it.get('tags'):
            lines.append('标签：' + ', '.join(it['tags']))
        if it.get('DOI'):
            lines.append('DOI：' + it['DOI'])
        lines.append(f"key：{it.get('key')}")
        lines.append('')
    return '\n'.join(lines).rstrip()


def render_item(detail):
    """`item()` 的结果 → markdown。"""
    simp = detail['item']
    lines = [f"# {simp.get('title') or '(无标题)'}"]
    for label, val in (('日期', simp.get('date')),
                       ('作者', '; '.join(simp.get('creators') or [])),
                       ('期刊/来源', simp.get('publicationTitle')),
                       ('DOI', simp.get('DOI')),
                       ('URL', simp.get('url')),
                       ('标签', ', '.join(simp.get('tags') or []))):
        if val:
            lines.append(f'{label}：{val}')
    lines.append(f"key：{simp.get('key')}")
    if detail['attachments']:
        lines += ['', '附件：']
        for a in detail['attachments']:
            lines.append(f"  - {a.get('title') or '(无标题)'} "
                         f"[{a.get('contentType')}] {a['key']}")
    lines.append(f"笔记数：{detail['notes_count']}")
    lines.append('')
    if detail['pdf_path']:
        lines.append(f"正文 PDF：{detail['pdf_path']}（附件 {detail['pdf_attachment_key']}）")
    else:
        lines.append('正文 PDF：未找到（可能没有 PDF 附件，或只有补充材料）')
    return '\n'.join(lines)


def render_collections(cols):
    """合集列表 → 带缩进的树。"""
    by_parent = {}
    for c in cols:
        by_parent.setdefault(c['parent'], []).append(c)

    def walk(parent):
        out = []
        for c in sorted(by_parent.get(parent, []), key=lambda x: x['name'] or ''):
            out.append(f"- {c['name']} ({c['key']})")
            out += ['  ' + l for l in walk(c['key'])]
        return out

    return '\n'.join([f'共 {len(cols)} 个合集：', ''] + walk(None))


def render_tags(rows):
    """标签列表 → markdown。"""
    if not rows:
        return '（没有标签）'
    return '标签（按文献数降序）：\n' + '\n'.join(
        f"- {r['tag']}（{r['numItems']} 篇）" for r in rows)
