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
VERSION = '0.2.0'

# 原样借用的（输出本来就合适）
BORROW = ('paperdb_sql', 'paperdb_measurements', 'ping')

MAX_DOIS = 25          # 一次提交的上限；与 getpdf 单次最多 25 篇的老约定一致
MAX_WAIT = 30          # fulltext_status 最多等多久（HTTP 服务一次只跑一个调用，等太久会堵别人）
STALE_SECS = 600       # 进度文件多久没动就当那个作业已经死了

INSTRUCTIONS = """\
材料学研究者（聚硼硅氧烷 / 动态键弹性体）的文献证据库，约 1100 篇，跑在他校园网里的主力机上。
检索你自己来；这里给你：付费全文（学校订阅）、库索引、向量检索、按节读、原件路径、抽出来的数值库。
每个工具都返回 structuredContent（JSON）；itemKey 可以给证据库 id，也可以直接给 DOI。
取全文：串行、每篇隔 20 秒、同时只跑一个作业（服务端强制，保护全校出口 IP），一篇约 1 分钟。
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
    data = {'itemKey': pid, 'available': True, 'main': slim(d)}
    if d.get('si'):
        data['si'] = slim(d['si'])         # SI 的地址与正文同形（s4.p1），取时传 si=true
    return _out('%s：正文 %d 节%s' % (pid, len(data['main']['sections']),
                                   '，另有 SI（取 SI 的节传 si=true）' if d.get('si') else ''), data)


def _one_section(req, max_chars):
    from tools import library
    pid = _resolve(req.get('itemKey'))
    r = library.section(pid, req.get('sectionId') or '', max_chars=max_chars, si=bool(req.get('si')))
    return {'itemKey': pid, 'sectionId': req.get('sectionId'), 'si': bool(req.get('si')),
            'text': r.get('text', ''), 'chars': r.get('chars', 0),
            'truncated': bool(r.get('truncated')), 'why_empty': r.get('why_empty', '')}


def _section(a):
    max_chars = int(a.get('maxChars') or 20000)
    reqs = a.get('requests') or ([{'itemKey': a.get('itemKey'), 'sectionId': a.get('sectionId'),
                                   'si': a.get('si')}] if a.get('itemKey') else [])
    if not reqs:
        raise ValueError('给 itemKey + sectionId，或 requests=[{itemKey, sectionId, si}]')
    out = []
    for q in reqs[:50]:
        try:
            out.append(_one_section(q, max_chars))
        except ValueError as e:
            out.append({'itemKey': q.get('itemKey'), 'sectionId': q.get('sectionId'),
                        'text': '', 'chars': 0, 'why_empty': str(e)})
    got = sum(1 for r in out if r['chars'])
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

def _fulltext(a):
    from shared.kernel import paths, subproc
    dois, bad = [], []
    for d in a.get('dois') or []:
        n = norm_doi(str(d))
        (dois if n else bad).append(n or str(d))
    dois = list(dict.fromkeys(dois))          # 队列内去重
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
                    {'results': [_slim_result(r) for r in rs], 'rejected': bad})
    path = _progress_path()
    try:
        io.open(path, 'w', encoding='utf-8').write(json.dumps(
            {'total': len(dois), 'finished': 0, 'done': False, 'elapsed': 0, 'results': []}))
    except OSError:
        pass
    subproc.spawn([sys.executable, '-m', 'tools.getpdf'] + dois
                  + ['--fulltext', '--limit', str(len(dois)), '--no-zotero'], cwd=paths.ROOT)
    eta = len(dois) * 60
    return _out('已提交 %d 篇，后台串行，预计约 %d 分钟' % (len(dois), max(1, eta // 60)),
                {'submitted': dois, 'rejected': bad, 'eta_s': eta})


def _slim_result(r):
    return {k: r.get(k) for k in ('doi', 'id', 'ok', 'source', 'secs', 'chars', 'si', 'why')}


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
            'elapsed_s': d.get('elapsed', 0), 'results': results}
    if a.get('brief') is False:
        from tools.getpdf import fulltext as F
        data['menus'] = {r['id']: F._menu_of(r['id']) for r in results if r.get('ok')}
    return _out('%d/%d 篇%s' % (data['finished'], data['total'], '，完成' if data['done'] else '，还在跑'), data)


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
    ('library_section', '按地址取原文：s5 一节（含子节）/ s5.p3 一段 / t1 一张表（HTML）/ f2 一条图注；SI 的传 si=true。'
     '可批量：requests=[{itemKey, sectionId, si}]（最多 50 处）。',
     {'itemKey': _KEY, 'sectionId': {'type': 'string'}, 'si': {'type': 'boolean'},
      'requests': {'type': 'array', 'items': {'type': 'object'}},
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
    ('fulltext_status', '取全文作业的进度。wait_s（≤30）= 等到有新一篇完成再回；brief=false 附每篇的骨架菜单。',
     {'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': MAX_WAIT}, 'brief': {'type': 'boolean'}},
     [], _status),
]


def build(full):
    """装成给 Claude Science 的服务：自己的 9 个 + 从完整服务 `full` 借的 3 个。"""
    s = MCPStdioServer(NAME, VERSION, instructions=INSTRUCTIONS)
    for name, desc, props, req, fn in TOOLS:
        s.register_tool(name, desc, {'type': 'object', 'properties': props, 'required': req}, fn)
    have = {t['name']: t for t in full._tools}
    missing = [n for n in BORROW if n not in have]
    if missing:
        # 借不到 = 某个工具包没挂上；喊出来，别让它悄悄少一个工具（踩坑 #173 同类）
        print(f'⚠ /science 少了这些工具（完整服务里没有）：{", ".join(missing)}', file=sys.stderr)
    for n in BORROW:
        t = have.get(n)
        if t:
            s.register_tool(n, t['description'], t['inputSchema'], t['handler'])  # 不打 confirm
    return s
