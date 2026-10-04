# -*- coding: utf-8 -*-
"""host.mcp.science · 给 Claude Science 的精简入口（HTTP 端点 `/science`）。

## 为什么单开一个（2026-09-29 用户定）

用户的判断：**Claude 这样的模型不需要一堆规矩，能拿到文献就够了。**
Claude Science 自己会检索（它有 OpenAlex），它缺的是：付费墙后面的全文（这台主力机的
校园网出口 + 过过人机验证的浏览器 + MineRU 解析）、以及用户这 1100 篇证据库的索引与向量库。

## 它怎么连进来（2026-09-29 实测出来的，别再猜）

Claude Science 的 Remote 连接器只收公网 https；本机命令连接器跑在它的沙箱里（读不到 D 盘、
**硬性禁止连回环地址**）。唯一可用的是它的 **SSH 算力**（B 机 WSL 的 science 账号）：
`~/bin/litplatform` 经一把受限钥匙登 B 的 Windows，只会跑 `bridge.py` → 本端点。
所以对它来说**每次调用 = 一次 SSH 命令**，它读的是**原始 JSON-RPC 回复**。

## v0.2（2026-09-30）：按它自己的实测评估改（桌面 litplatform_assessment.md）

它的原话要点：回复里的每个字都进它的上下文；排好版的中文它得用正则抠 id；
20 篇要拆 7 轮「提交 → 轮询」；轮询每次都带一整份菜单。于是：

- **每个工具都给 `structuredContent`**，文字只留一两行摘要。配套 `litcall.py` 只打印结构化那份。
- **itemKey 一律可给 DOI**（含 `https://doi.org/…`、`doi:` 前缀），服务端对账。
- `paper_fulltext` 一次最多 25 篇（原来 3 篇是接口层的限制，不是风控要求；风控靠的是
  串行 + 20 秒间隔 + 同时只一个作业，这三条一条没松）。
- `fulltext_status` 加 `wait_s`（等到有进展再回，最多 30 秒）与 `brief`（默认只回状态，不带菜单）。
- `library_section` 可批量：`requests=[{itemKey, sectionId, si}]`。
- 新增 `library_manifest`：全库清单写成 JSON 文件，回路径 —— 它在 B 上自己做集合运算。
- `paper_files` 多给图片目录与「图号 → 图片文件」对照。
- `library_refs` 加回来（09-29 我以为它用 OpenAlex 就够、删了，它明说要）。
- 借 `paperdb_sql` / `paperdb_measurements`：抽出来的数值库，只读。

## 唯一的规矩在服务端

取全文串行、每篇隔 20 秒、**同一时刻只许一个取全文作业**。出版商风控封的是整个学校的出口 IP。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

import io
import json
import re
import time

from host.mcp.stdio import MCPStdioServer

ENDPOINT = '/science'
NAME = 'literature-science'
VERSION = '0.3.0'
# v0.3（2026-10-04，桌面 literature_platform_spec_for_agent.md 的 P0 + 部分 P1/P2）：
#   解析分两层（PDF 到手几秒出快速文本层，MineRU 后台补表格）· 结果带 code/retryable/stage/tier/route ·
#   撞人机验证同家暂缓、别家照跑、主力机桌面弹提醒、fulltext_retry 续跑 · 任何返回超 50 KB 落文件只回路径 ·
#   library_section 加 offset 分页、表格出 CSV/JSON · 提交前问 Crossref，无效 DOI 当场 NOT_FOUND ·
#   新增 paper_status（一次看清一批的档位）· outline 带 tier 与图片路径

# 原样借用的（输出本来就合适）
BORROW = ('paperdb_sql', 'paperdb_measurements', 'ping')

MAX_DOIS = 25          # 一次提交的上限；与 getpdf 单次最多 25 篇的老约定一致
MAX_WAIT = 30          # fulltext_status 最多等多久（HTTP 服务一次只跑一个调用，等太久会堵别人）
STALE_SECS = 600       # 进度文件多久没动就当那个作业已经死了
STALL_SECS = 300       # 同一篇处理超过这么久没进展 → 状态里标 stalled（下载各步自带超时，正常到不了这么久）
MAX_OUT = 50000        # 一次返回的结构化数据上限（字节）：调用方的远程命令输出过 64 KB 就被截断（2026-10 实测）

INSTRUCTIONS = """\
材料学研究者（聚硼硅氧烷 / 动态键弹性体）的文献证据库，约 1100 篇，跑在他校园网里的主力机上。
检索你自己来；这里给你：付费全文（学校订阅）、库索引、向量检索、按节读、原件路径、抽出来的数值库。
每个工具都返回 structuredContent（JSON）；itemKey 可以给证据库 id，也可以直接给 DOI。
取全文：串行、每篇隔 20 秒、同时只跑一个作业（服务端强制，保护全校出口 IP），一篇约 1 分钟。
PDF 到手几秒内先出 tier=text（本地抽字，可按节读、无表格结构）；MineRU 后台补成 tier=structured（含表格）。
每篇结果带 code（OK / CAPTCHA_REQUIRED / NOT_SUBSCRIBED / NOT_FOUND / NO_PDF_LINK / PARSE_PENDING /
PARSE_FAILED / NETWORK_ERROR / NOT_FETCHED）与 retryable；CAPTCHA_REQUIRED 等人在主力机浏览器点完后用 fulltext_retry。
任何返回超过 50 KB 会写成文件、只回 spilled 路径。
文件路径是 B 机 WSL 路径（/mnt/d/...），你的 SSH 算力能直接读。"""

_DOI_PREFIX = re.compile(r'(?i)^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)')


# ══════════════════════════════════════════════════════════════════════
# 小工具
# ══════════════════════════════════════════════════════════════════════

def _progress_path():
    from shared.kernel import paths
    return paths.runtime('fulltext_progress.json')


def _read_progress(path=None):
    path = path or _progress_path()
    if not os.path.exists(path):
        return None
    try:
        return json.load(io.open(path, encoding='utf-8'))
    except Exception:
        return {'total': 0, 'finished': 0, 'done': False, 'results': [], '_writing': True}


def running_job(path=None, now=None):
    """有没有一个取全文作业正在跑 → 给人看的一句话，或 ''。

    判据：进度文件存在、`done` 为假、而且最近 STALE_SECS 秒内还写过（死掉的作业不挡路）。
    """
    path = path or _progress_path()
    d = _read_progress(path)
    if d is None:
        return ''
    if d.get('_writing'):
        return '有一个取全文作业正在写进度'
    if d.get('done'):
        return ''
    if (now or time.time()) - os.path.getmtime(path) > STALE_SECS:
        return ''
    return '上一个取全文作业还在跑（%d/%d 篇）' % (d.get('finished', 0), d.get('total', 0))


def to_wsl(path):
    """Windows 路径 → WSL 里看到的路径（D:\\a\\b → /mnt/d/a/b）。不是盘符路径就原样返回。"""
    p = (path or '').replace('\\', '/')
    if len(p) >= 2 and p[1] == ':':
        return '/mnt/' + p[0].lower() + p[2:]
    return p


def norm_doi(k):
    """去掉 https://doi.org/ 与 doi: 前缀；不是 DOI 返回 ''。"""
    k = _DOI_PREFIX.sub('', (k or '').strip())
    return k if k.startswith('10.') and '/' in k else ''


def _resolve(k):
    """itemKey → 证据库 id。可以是 id，也可以是 DOI（带不带 doi.org 前缀都行）。"""
    from shared.kernel import catalog, paths
    k = (k or '').strip()
    doi = norm_doi(k)
    if doi:
        pid = catalog.find(doi)
        if not pid:
            raise ValueError(f'证据库里没有 DOI {doi}（用 paper_fulltext 把它拿进来）')
        return pid
    try:
        return paths.check_key(k)
    except paths.BadKeyError:
        raise ValueError(f'「{k}」既不是证据库 id 也不是 DOI')


def _out(text, data):
    return {'text': text, 'structured': data}


# ══════════════════════════════════════════════════════════════════════
# 库：有没有 / 全库清单 / 按意思找
# ══════════════════════════════════════════════════════════════════════

# 不带 in_zotero：Claude Science 那条路不跟 Zotero 扯上关系（2026-09-30 用户定）
_CARD_KEYS = ('id', 'doi', 'title', 'year', 'journal', 'pdf', 'si',
              'fulltext', 'si_fulltext', 'summary', 'structured')


def _card(r):
    return {k: r.get(k) for k in _CARD_KEYS}


def _db_search(a):
    from tools import library
    q = (a.get('query') or '').strip()
    doi = norm_doi(q)
    rows = library.db_search(doi or q, limit=int(a.get('limit') or 25))
    return _out('%d 篇匹配「%s」' % (len(rows), q), {'papers': [_card(r) for r in rows]})


def manifest_rows():
    from shared.kernel import catalog
    return [_card(r) for r in catalog.scan()]


def _manifest(a):
    from shared.kernel import paths
    rows = manifest_rows()
    path = paths.runtime('library_manifest.json')
    io.open(path, 'w', encoding='utf-8').write(json.dumps(
        {'generated': time.strftime('%Y-%m-%d %H:%M:%S'), 'fields': list(_CARD_KEYS), 'papers': rows},
        ensure_ascii=False))
    n = lambda k: sum(1 for r in rows if r.get(k))
    stats = {'papers': len(rows), 'with_doi': n('doi'), 'pdf': n('pdf'), 'si': n('si'),
             'fulltext': n('fulltext'), 'summary': n('summary'), 'structured': n('structured')}
    return _out('全库清单 %d 篇 → %s' % (len(rows), to_wsl(path)),
                {'path': to_wsl(path), 'fields': list(_CARD_KEYS), 'stats': stats,
                 # 口径（2026-09-30 复测提的）：这里是证据库目录（有正本 / 全文的库）；paperdb 的 papers 表
                 # 另含只有摘要的 OpenAlex 层，所以行数多得多；统计请用视图 papers_canonical
                 'scope': 'evidence library (papers with PDF/full text). paperdb.papers additionally holds '
                          'abstract-only rows (OpenAlex); use view papers_canonical for one row per DOI.'})


def dedupe_hits(rows):
    """同一篇存了两份（Zotero 编号与 doi_ 各一份）时，同一段会出现两次 —— 按 DOI + 开头去重。"""
    seen, out = set(), []
    for r in rows:
        key = ((r.get('doi') or r.get('id') or '').lower(), (r.get('text') or '')[:200])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _retrieve(a):
    from tools import library
    n = int(a.get('n') or 8)
    rows = library.retrieve(a['query'], n=n + 4, where=a.get('where') or 'all')
    rows = dedupe_hits(rows)[:n]
    return _out('%d 段最相近「%s」' % (len(rows), a['query']), {'hits': rows})


# ══════════════════════════════════════════════════════════════════════
# 读：骨架 / 节（可批量）/ 参考文献 / 文件
# ══════════════════════════════════════════════════════════════════════

def _outline(a):
    from tools import library
    pid = _resolve(a.get('itemKey'))
    d = library.outline(pid)
    if not d.get('available'):
        return _out('%s：%s' % (pid, d.get('why', '没有骨架')), {'itemKey': pid, 'available': False})
    slim = lambda o: {
        'sections': [{k: s.get(k) for k in ('id', 'title', 'kind', 'chars', 'n_numbers', 'n_tables', 'n_figures')}
                     | ({'paras': [{k: p[k] for k in ('id', 'chars', 'head')} for p in s['paras']]}
                        if s.get('paras') else {})
                     for s in o.get('sections') or []],
        'tables': [{k: t.get(k) for k in ('id', 'ref', 'caption', 'section', 'n_rows', 'n_cols')}
                   for t in o.get('tables') or []],
        'figures': [{k: f.get(k) for k in ('id', 'ref', 'caption', 'section')} for f in o.get('figures') or []],
        'chars': (o.get('stats') or {}).get('chars', 0)}
    from tools.getpdf import fulltext as F
    data = {'itemKey': pid, 'available': True, 'main': slim(d), 'tier': F.tier_of(pid)}
    # 图注带上图片路径（只有 MineRU 那一档有图片；快速文本层只有图注）
    imgs = _figure_map(pid)
    for f in data['main']['figures']:
        f['image'] = imgs.get(_fig_key(f.get('ref')), '')
    if d.get('si'):
        data['si'] = slim(d['si'])         # SI 的地址与正文同形（s4.p1），取时传 si=true
        data['si_tier'] = F.tier_of(pid, si=True)
    return _out('%s：正文 %d 节%s' % (pid, len(data['main']['sections']),
                                   '，另有 SI（取 SI 的节传 si=true）' if d.get('si') else ''), data)


def _fig_key(ref):
    """'Figure 3' / 'Fig. 3b' / 'Scheme 1' → 'figure 3' / 'scheme 1'（对图号用）。"""
    r = re.sub(r'\s+', ' ', (ref or '').lower().replace('fig.', 'figure').replace('fig ', 'figure ')).strip()
    return re.sub(r'(\d)[a-z]$', r'\1', r.rstrip('.'))


def _figure_map(pid):
    """这篇「图号 → 图片 WSL 路径」。没有 MineRU 图片目录时是空的。"""
    from shared.kernel import paths
    md, img = paths.fulltext(pid), paths.images_dir(pid)
    if not (os.path.exists(md) and os.path.isdir(img)):
        return {}
    text = io.open(md, encoding='utf-8').read()
    return {_fig_key(f['ref']): to_wsl(f['image']) for f in figure_images(text, img)}


def _html_cells(html):
    """HTML 表格 → [[{text, colspan, rowspan}, …], …]（标准库 html.parser）。"""
    from html.parser import HTMLParser
    rows = []
    st: dict = {'row': None, 'cell': None}

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == 'tr':
                st['row'] = []
            elif tag in ('td', 'th') and st['row'] is not None:
                st['cell'] = {'text': '', 'colspan': int(a.get('colspan') or 1),
                              'rowspan': int(a.get('rowspan') or 1)}
            elif tag == 'br' and st['cell'] is not None:
                st['cell']['text'] += ' '

        def handle_endtag(self, tag):
            if tag in ('td', 'th') and st['cell'] is not None and st['row'] is not None:
                st['row'].append(st['cell'])
                st['cell'] = None
            elif tag == 'tr' and st['row'] is not None:
                rows.append(st['row'])
                st['row'] = None

        def handle_data(self, data):
            if st['cell'] is not None:
                st['cell']['text'] += data

    P().feed(html or '')
    return rows


def html_table_rows(html):
    """HTML 表格 → 规整的行列表：colspan 展开成重复格，rowspan 往下面几行补同一格。"""
    grid, carry = [], {}                       # carry：列号 → (还要补几行, 文字)
    for cells in _html_cells(html):
        line, col, cells = [], 0, list(cells)
        while cells or carry.get(col):
            if carry.get(col):
                left, txt = carry[col]
                line.append(txt)
                carry[col] = (left - 1, txt) if left > 1 else None
                col += 1
                continue
            c = cells.pop(0)
            txt = ' '.join(c['text'].split())
            for _ in range(max(1, c['colspan'])):
                line.append(txt)
                if c['rowspan'] > 1:
                    carry[col] = (c['rowspan'] - 1, txt)
                col += 1
        grid.append(line)
    return grid


def table_rows(text):
    """一段含 <table> 的文字 → (表前的图注文字, 行列表)。没有表格返回 (text, [])。"""
    m = re.search(r'(?is)<table\b.*?</table>', text or '')
    if not m:
        return text, []
    return text[:m.start()].strip(), html_table_rows(m.group(0))


def _as_csv(rows):
    import csv
    buf = io.StringIO()
    csv.writer(buf, lineterminator='\n').writerows(rows)
    return buf.getvalue()


def _one_section(req, max_chars, offset=0, fmt='html'):
    from tools import library
    pid = _resolve(req.get('itemKey'))
    offset = max(0, int(req.get('offset') or offset or 0))
    fmt = (req.get('format') or fmt or 'html').lower()
    r = library.section(pid, req.get('sectionId') or '', max_chars=offset + max_chars, si=bool(req.get('si')))
    full = r.get('text', '')
    out = {'itemKey': pid, 'sectionId': req.get('sectionId'), 'si': bool(req.get('si')),
           'why_empty': r.get('why_empty', '')}
    if fmt in ('csv', 'json') and full:
        caption, rows = table_rows(full)
        if rows:
            out.update(format=fmt, caption=caption, n_rows=len(rows), n_cols=max(len(x) for x in rows),
                       chars=len(full))
            out['csv' if fmt == 'csv' else 'rows'] = _as_csv(rows) if fmt == 'csv' else rows
            return out
        out['format_note'] = '这处没有 HTML 表格（快速文本层没有表格结构，等 tier=structured），按文字给'
    text = full[offset:offset + max_chars]
    more = bool(r.get('truncated')) or len(full) > offset + max_chars
    out.update(text=text, chars=len(text), offset=offset, truncated=more)
    if more:
        out['next_offset'] = offset + len(text)
    return out


def _section(a):
    max_chars = int(a.get('maxChars') or 20000)
    reqs = a.get('requests') or ([{'itemKey': a.get('itemKey'), 'sectionId': a.get('sectionId'),
                                   'si': a.get('si')}] if a.get('itemKey') else [])
    if not reqs:
        raise ValueError('给 itemKey + sectionId，或 requests=[{itemKey, sectionId, si}]')
    out = []
    for q in reqs[:50]:
        try:
            out.append(_one_section(q, max_chars, a.get('offset') or 0, a.get('format') or 'html'))
        except ValueError as e:
            out.append({'itemKey': q.get('itemKey'), 'sectionId': q.get('sectionId'),
                        'text': '', 'chars': 0, 'why_empty': str(e)})
    got = sum(1 for r in out if r.get('chars'))
    return _out('取到 %d/%d 处' % (got, len(out)), {'results': out})


def crossref_refs(doi, fetch=None):
    """出版社在 Crossref 登记的参考文献（有序，常带 DOI）→ [{n, doi, text}]。取不到返回 []。"""
    if not doi:
        return []
    try:
        if fetch is None:
            from shared.adapters import crossref
            fetch = crossref.work
        items = fetch(doi).get('reference') or []
    except Exception:
        return []
    out = []
    for i, r in enumerate(items, 1):
        text = r.get('unstructured') or ', '.join(
            str(x) for x in (r.get('author'), r.get('year'), r.get('article-title'), r.get('journal-title')) if x)
        out.append({'n': i, 'doi': (r.get('DOI') or '').lower(), 'text': text[:300]})
    return out


def enrich_refs(rows, cr, by_doi):
    """正文抽的参考文献缺 DOI 时，用 Crossref 那份补。**条数对得上才按顺序补**；对不上不硬对（返回 False）。"""
    if not cr or len(cr) != len(rows):
        return False
    for r, c in zip(rows, cr):
        if not r.get('doi') and c['doi']:
            r['doi'], r['doi_from'] = c['doi'], 'crossref'
            pid = by_doi.get(c['doi'], '')
            if pid:
                r['in_db'], r['id'] = True, pid
    return True


def _refs(a):
    from shared.kernel import catalog
    from tools import library
    pid = _resolve(a.get('itemKey'))
    rows = library.refs(pid)
    data = {'itemKey': pid, 'refs': rows}
    # 正文里抽到的 DOI 不到一半 → 去 Crossref 取出版社登记的那份（2026-09-30 复测：有的篇 59 条 0 个 DOI）
    if rows and sum(1 for r in rows if r.get('doi')) * 2 < len(rows):
        cr = crossref_refs(catalog.doi_of(catalog.read_meta(pid)))
        if cr:
            aligned = enrich_refs(rows, cr, catalog.by_doi())
            data['crossref_aligned'] = aligned
            if not aligned:
                data['crossref'] = cr        # 条数对不上：两份都给，由你对
    n_doi = sum(1 for r in rows if r.get('doi'))
    return _out('%s：%d 条参考文献（%d 条有 DOI），%d 条已在证据库' % (
        pid, len(rows), n_doi, sum(1 for r in rows if r.get('in_db'))), data)


_IMG_LINE = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')
_CAP_LINE = re.compile(r'(?im)^\s*(?:\*\*)?((?:Fig(?:ure)?|Scheme)\.?\s*S?\d+)')


def figure_images(md, img_dir):
    """全文 Markdown → [{ref, image}]：每条图注（Figure N / Fig. N / Scheme N）之前最近的那张图。

    MineRU 的写法是「图片行 → 图注」，所以按行走一遍、记住上一张图即可。纯文本处理，不看图。
    """
    out, last, seen = [], '', set()
    for line in (md or '').splitlines():
        m = _IMG_LINE.search(line)
        if m:
            last = m.group(1)
        c = _CAP_LINE.match(line)
        if c and last:
            ref = re.sub(r'\s+', ' ', c.group(1)).replace('Fig.', 'Figure').replace('Fig ', 'Figure ')
            if ref.lower() not in seen:
                seen.add(ref.lower())
                out.append({'ref': ref, 'image': os.path.join(img_dir, os.path.basename(last))})
            last = ''
    return out


def paper_files(key):
    """这篇手上有哪些文件 → {名字: Windows 路径}。只列真在盘上的。"""
    from shared.kernel import paths
    cands = {'main_pdf': paths.local_pdf(key), 'si_original': paths.find_local_si(key),
             'main_md': paths.fulltext(key), 'si_md': paths.si_fulltext(key),
             'images_dir': paths.images_dir(key), 'summary_html': paths.summary(key)}
    return {k: p for k, p in cands.items() if p and os.path.exists(p)}


def _paper_files(a):
    pid = _resolve(a.get('itemKey'))
    got = paper_files(pid)
    data = {'itemKey': pid, 'files': {k: to_wsl(p) for k, p in got.items()}, 'figures': []}
    if 'main_md' in got and 'images_dir' in got:
        md = io.open(got['main_md'], encoding='utf-8').read()
        data['figures'] = [{'ref': f['ref'], 'image': to_wsl(f['image'])}
                           for f in figure_images(md, got['images_dir'])]
    return _out('%s：%d 个文件，%d 张图对上了图号' % (pid, len(got), len(data['figures'])), data)


# ══════════════════════════════════════════════════════════════════════
# 取全文：提交（后台串行）+ 看进度（可等）
# ══════════════════════════════════════════════════════════════════════

def precheck(dois, exists_fn=None):
    """库里没有的 DOI 先问 Crossref：查无此 DOI 的当场退回（NOT_FOUND，不占队列）。

    → (要交的, 退回的 [{doi, code, why}])。Crossref 连不上 / 别的错一律放行 —— 预检只拦「确定不存在」的，
    拿不准就交给出版商那边判（宁可多跑一篇，不能误杀）。并发问（5 路），25 篇约几秒。
    """
    from shared.kernel import catalog
    lookup = exists_fn
    if lookup is None:
        from shared.adapters import crossref

        def _exists(d):
            try:
                crossref.work(d)
                return True
            except crossref.DoiNotFound:
                return False
            except Exception:
                return True
        lookup = _exists
    todo = [d for d in dois if not catalog.find(d)]
    if not todo:
        return list(dois), []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=5) as ex:
        exists = dict(zip(todo, ex.map(lookup, todo)))
    keep = [d for d in dois if exists.get(d, True)]
    gone = [{'doi': d, 'code': 'NOT_FOUND', 'retryable': False,
             'why': 'Crossref 查无此 DOI（多半抄错了），没排进队列'} for d in dois if not exists.get(d, True)]
    return keep, gone


def _fulltext(a):
    from shared.kernel import paths, subproc
    dois, bad = [], []
    for d in a.get('dois') or []:
        n = norm_doi(str(d))
        (dois if n else bad).append(n or str(d))
    dois = list(dict.fromkeys(dois))          # 队列内去重
    rejected = [{'doi': d, 'code': 'NOT_FOUND', 'retryable': False, 'why': '不像一个 DOI'} for d in bad]
    if not dois:
        raise ValueError('没有像样的 DOI：%s' % ', '.join(bad) if bad else '没给 DOI')
    if len(dois) > MAX_DOIS:
        raise ValueError(f'一次最多 {MAX_DOIS} 篇（给了 {len(dois)}）；分批提交，上一批跑完再交下一批')
    allow = a.get('allowFetch', True)
    if allow:
        busy = running_job()
        if busy:
            raise ValueError(busy + '；等它跑完再提交（fulltext_status 可以 wait_s 等）')
    else:
        # 只查不取：前三层零成本，同步答
        from tools.getpdf import fulltext as F
        rs = F.many(dois, allow_fetch=False, limit=len(dois), use_zotero=False)
        return _out('只查不取：%d/%d 篇手上有全文' % (sum(1 for r in rs if r['ok']), len(rs)),
                    {'results': [_slim_result(r) for r in rs], 'rejected': rejected})
    dois, gone = precheck(dois)
    rejected += gone
    if not dois:
        return _out('全部退回：%d 篇 DOI 无效' % len(rejected), {'submitted': [], 'rejected': rejected, 'eta_s': 0})
    path = _progress_path()
    try:
        io.open(path, 'w', encoding='utf-8').write(json.dumps(
            {'total': len(dois), 'finished': 0, 'done': False, 'elapsed': 0, 'results': []}))
    except OSError:
        pass
    subproc.spawn([sys.executable, '-m', 'tools.getpdf'] + dois
                  + ['--fulltext', '--limit', str(len(dois)), '--no-zotero'], cwd=paths.ROOT)
    eta = len(dois) * 60
    return _out('已提交 %d 篇，后台串行，预计约 %d 分钟%s' % (
        len(dois), max(1, eta // 60), '；退回 %d 篇' % len(rejected) if rejected else ''),
                {'submitted': dois, 'rejected': rejected, 'eta_s': eta})


_RESULT_KEYS = ('doi', 'id', 'ok', 'code', 'retryable', 'stage', 'tier', 'route', 'source',
                'secs', 'chars', 'si', 'why', 'deferred')


def _slim_result(r):
    out = {k: r.get(k) for k in _RESULT_KEYS if k in r}
    if out.get('id'):
        # 档位看盘、现算：MineRU 在后台把 text 升成 structured，进度文件里那份是提交时的
        from tools.getpdf import fulltext as F
        try:
            out['tier'] = F.tier_of(out['id'])
            out['si_tier'] = F.tier_of(out['id'], si=True)
        except Exception:
            pass
        if out.get('code') == 'PARSE_PENDING' and out.get('tier') in ('text', 'structured'):
            out.update(ok=True, code='OK', retryable=False, why='')
    return out


def _status(a):
    wait = max(0, min(int(a.get('wait_s') or 0), MAX_WAIT))
    d = _read_progress()
    if d is None:
        return _out('还没有提交过取全文', {'total': 0, 'finished': 0, 'done': True, 'results': []})
    t_end, seen = time.time() + wait, d.get('finished', 0)
    while wait and not d.get('done') and time.time() < t_end:
        time.sleep(2)
        d = _read_progress() or d
        if d.get('finished', 0) != seen:
            break
    results = [_slim_result(r) for r in d.get('results') or []]
    data = {'total': d.get('total', 0), 'finished': d.get('finished', 0), 'done': bool(d.get('done')),
            'elapsed_s': d.get('elapsed', 0), 'results': results,
            'retryable': [r['doi'] for r in results if r.get('retryable') and not r.get('ok')]}
    if d.get('upgrading'):
        data['upgrading'] = True               # 下载完了，MineRU 还在后台补表格；结果里的 tier 会自己变
    if d.get('current') and not d.get('done'):
        # 正在处理哪篇、已经多久（每 15 秒更新）—— 解析一篇大文献要好几分钟，这个数在涨就说明没卡死
        data['current'] = d['current']
        if (d['current'].get('for_s') or 0) > STALL_SECS:
            data['stalled'] = True
            data['stalled_hint'] = '同一篇处理了 %d 秒还没完：多半是浏览器那边卡在验证页，看主力机桌面提醒' % d['current']['for_s']
    if a.get('brief') is False:
        from tools.getpdf import fulltext as F
        data['menus'] = {r['id']: F._menu_of(r['id']) for r in results if r.get('ok')}
    return _out('%d/%d 篇%s' % (data['finished'], data['total'], '，完成' if data['done'] else '，还在跑'), data)


def _retry(a):
    """上一个作业里可重试的（撞验证 / 暂缓 / 网络错）再交一次。也可以自己给 dois。"""
    dois = a.get('dois')
    if not dois:
        d = _read_progress() or {}
        dois = [r['doi'] for r in d.get('results') or []
                if not r.get('ok') and (r.get('retryable') or r.get('code') in ('CAPTCHA_REQUIRED', 'NETWORK_ERROR'))]
    if not dois:
        return _out('上一个作业里没有可重试的', {'submitted': [], 'rejected': [], 'eta_s': 0})
    return _fulltext({'dois': dois})


def _paper_status(a):
    """一批 DOI / id → 每篇的档位、SI、表图数、最近一次错误。不取、不解析、零成本。"""
    from shared.kernel import catalog, paths
    from tools import library
    from tools.getpdf import fulltext as F
    keys = list(a.get('dois') or []) + list(a.get('itemKeys') or [])
    if not keys:
        raise ValueError('给 dois=[…] 或 itemKeys=[…]')
    last = {r.get('doi'): r for r in ((_read_progress() or {}).get('results') or [])}
    out = []
    for k in keys[:200]:
        doi = norm_doi(str(k))
        try:
            pid = _resolve(k)
        except ValueError:
            row = {'key': k, 'doi': doi, 'in_db': False, 'tier': 'none'}
            if doi in last:
                row.update(last_code=last[doi].get('code'), last_why=last[doi].get('why'))
            out.append(row)
            continue
        row = {'key': k, 'id': pid, 'doi': doi or catalog.doi_of(catalog.read_meta(pid)), 'in_db': True,
               'pdf': os.path.exists(paths.local_pdf(pid)), 'si_original': bool(paths.find_local_si(pid)),
               'tier': F.tier_of(pid), 'si_tier': F.tier_of(pid, si=True)}
        if row['tier'] != 'none':
            try:
                o = library.outline(pid)
                row.update(sections=len(o.get('sections') or []), tables=len(o.get('tables') or []),
                           figures=len(o.get('figures') or []))
            except Exception:
                pass
        if row['doi'] in last:
            r = last[row['doi']]
            row.update(route=r.get('route') or r.get('source'), last_code=r.get('code'))
            if not r.get('ok'):
                row['last_why'] = r.get('why')
        out.append(row)
    n = lambda t: sum(1 for r in out if r.get('tier') == t)
    return _out('%d 篇：structured %d、text %d、没有可读全文 %d' % (len(out), n('structured'), n('text'), n('none')),
                {'papers': out})


def cap(name, handler, limit=None, spill_dir=None):
    """包一层：结构化结果超过 MAX_OUT 字节就写成文件、只回路径（2026-10：6 篇 outline 合一次 batch，
    JSON 在 64 KB 处被截成半截）。文件在 logs/science_out/，B 机 WSL 读得到。"""
    limit = limit or MAX_OUT

    def h(a):
        r = handler(a)
        data = r.get('structured') if isinstance(r, dict) else None
        if data is None:
            return r
        raw = json.dumps(data, ensure_ascii=False)
        size = len(raw.encode('utf-8'))
        if size <= limit:
            return r
        from shared.kernel import paths
        d = spill_dir or paths.runtime('science_out')
        os.makedirs(d, exist_ok=True)
        _sweep(d)
        p = os.path.join(d, '%s-%s-%d.json' % (name, time.strftime('%Y%m%d-%H%M%S'), int(time.time() * 1000) % 1000))
        io.open(p, 'w', encoding='utf-8').write(raw)
        summary = {k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in data.items()
                   if not isinstance(v, str) or len(v) < 200}
        return _out('%s：结果 %d 字节，超过 %d，已写到 %s' % (r.get('text', ''), size, limit, to_wsl(p)),
                    {'spilled': to_wsl(p), 'bytes': size, 'summary': summary,
                     'hint': '整份结果在 spilled 文件里（JSON）；或者缩小请求（少几处 / maxChars / offset 分页）'})
    return h


def _sweep(d, keep_s=3 * 86400):
    """落出来的大结果留三天。"""
    now = time.time()
    try:
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if now - os.path.getmtime(p) > keep_s:
                os.remove(p)
    except OSError:
        pass


# ══════════════════════════════════════════════════════════════════════
# 装配
# ══════════════════════════════════════════════════════════════════════

_KEY = {'type': 'string', 'description': '证据库 id 或 DOI'}

TOOLS = [
    ('library_db_search', '证据库里有没有：按标题 / DOI / 期刊子串搜，回目录卡（有无正文、SI、已解析、已精读、已结构化）。',
     {'query': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200}}, ['query'], _db_search),
    ('library_manifest', '全库清单写成 JSON 文件（每篇 id/DOI/标题/年份/期刊/有什么），回文件路径与统计。',
     {}, [], _manifest),
    ('library_retrieve', '向量检索证据库：最相近的段落 + 文献 id + 节地址（拿去 library_section 读上下文）。',
     {'query': {'type': 'string'}, 'n': {'type': 'integer', 'minimum': 1, 'maximum': 30},
      'where': {'type': 'string', 'enum': ['all', 'main', 'si']}}, ['query'], _retrieve),
    ('library_outline', '一篇的骨架：节 / 长节的段 / 表 / 图注，各自的地址、类别、字数。有 SI 的另给 si 一份。',
     {'itemKey': _KEY}, ['itemKey'], _outline),
    ('library_section', '按地址取原文：s5 一节（含子节）/ s5.p3 一段 / t1 一张表 / f2 一条图注；SI 的传 si=true。'
     '表格 format=csv|json（默认 html）。长的用 offset 分页（回 next_offset）。'
     '可批量：requests=[{itemKey, sectionId, si, offset, format}]（最多 50 处）。',
     {'itemKey': _KEY, 'sectionId': {'type': 'string'}, 'si': {'type': 'boolean'},
      'requests': {'type': 'array', 'items': {'type': 'object'}},
      'offset': {'type': 'integer', 'minimum': 0},
      'format': {'type': 'string', 'enum': ['html', 'csv', 'json']},
      'maxChars': {'type': 'integer', 'minimum': 100, 'maximum': 200000}}, [], _section),
    ('library_refs', '一篇的参考文献条目（带 DOI 的给 DOI），标出哪些已在证据库（in_db + id）。',
     {'itemKey': _KEY}, ['itemKey'], _refs),
    ('paper_files', '一篇手上的文件（正文 PDF / SI 原件 / 解析 Markdown / 图片目录 / 中文精读），B 机 WSL 路径；'
     '另给「图号 → 图片文件」对照。',
     {'itemKey': _KEY}, ['itemKey'], _paper_files),
    ('paper_fulltext', '给 DOI 取全文（学校订阅）→ 正本 + SI 落地并解析。后台串行跑，一次最多 25 篇，'
     '同一时刻只跑一个作业。allowFetch=false 只查手上有没有（同步、零成本）。',
     {'dois': {'type': 'array', 'items': {'type': 'string'}}, 'allowFetch': {'type': 'boolean'}},
     ['dois'], _fulltext),
    ('fulltext_status', '取全文作业的进度。每篇带 code / retryable / tier（现算）；retryable 列出可续跑的 DOI；'
     'stalled=true 表示同一篇卡太久。wait_s（≤30）= 等到有新一篇完成再回；brief=false 附每篇的骨架菜单。',
     {'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': MAX_WAIT}, 'brief': {'type': 'boolean'}},
     [], _status),
    ('fulltext_retry', '续跑：把上一个作业里撞人机验证 / 暂缓 / 网络错的再交一次（人在主力机浏览器点完验证后用）。'
     '也可以自己给 dois。规矩同 paper_fulltext。',
     {'dois': {'type': 'array', 'items': {'type': 'string'}}}, [], _retry),
    ('paper_status', '一批 DOI 或 id 的现状：在不在库、tier（none/text/structured）、SI、节 / 表 / 图数、'
     '上次取全文的 route 与错误码。零成本，不取不解析。',
     {'dois': {'type': 'array', 'items': {'type': 'string'}},
      'itemKeys': {'type': 'array', 'items': {'type': 'string'}}}, [], _paper_status),
]


def build(full):
    """装成给 Claude Science 的服务：自己的 11 个 + 从完整服务 `full` 借的 3 个。每个都套 50 KB 上限。"""
    s = MCPStdioServer(NAME, VERSION, instructions=INSTRUCTIONS)
    for name, desc, props, req, fn in TOOLS:
        s.register_tool(name, desc, {'type': 'object', 'properties': props, 'required': req}, cap(name, fn))
    have = {t['name']: t for t in full._tools}
    missing = [n for n in BORROW if n not in have]
    if missing:
        # 借不到 = 某个工具包没挂上；喊出来，别让它悄悄少一个工具（踩坑 #173 同类）
        print(f'⚠ /science 少了这些工具（完整服务里没有）：{", ".join(missing)}', file=sys.stderr)
    for n in BORROW:
        t = have.get(n)
        if t:
            s.register_tool(n, t['description'], t['inputSchema'], cap(n, t['handler']))  # 不打 confirm
    return s
