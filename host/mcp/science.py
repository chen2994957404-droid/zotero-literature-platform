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
VERSION = '0.6.1'
# v0.3（2026-10-04，桌面 literature_platform_spec_for_agent.md 的 P0 + 部分 P1/P2）：
#   解析分两层（PDF 到手几秒出快速文本层，MineRU 后台补表格）· 结果带 code/retryable/stage/tier/route ·
#   撞人机验证同家暂缓、别家照跑、主力机桌面弹提醒、fulltext_retry 续跑 · 任何返回超 50 KB 落文件只回路径 ·
#   library_section 加 offset 分页、表格出 CSV/JSON · 提交前问 Crossref，无效 DOI 当场 NOT_FOUND ·
#   新增 paper_status（一次看清一批的档位）· outline 带 tier 与图片路径
# v0.3.1（同日，它的实测报告 literature_platform_eval_2026-10-04.md）：
#   节号随 text→structured 升级会错位 → library_section 收 title / quote 找回现在的位置（remapped_from）、带 rev ·
#   图号对照改成整张图（版面坐标裁，image_kind=full）· 新增 figure_image（小 JPEG 直接回，不传文件）·
#   检索滤掉只有标题的碎片、per_paper · 表格 CSV 带图注 · 库内搜索不分横线写法 · ping 报自己的版本
# v0.4（2026-10-08 用户定）：chemdb_search / chemdb_page —— 借主力机浏览器搜 SciFinder / Reaxys、读结果页文字。
#   它进不去这两个库（学校订阅 + 个人登录），人一条条点开筛又太慢。按人的频率：两次至少隔 CHEMDB_GAP 秒、
#   每个库每天至多 CHEMDB_DAILY 次（服务端强制）。CAS 条款禁止脚本代替手工 —— 用户知情后决定小量用。
# v0.5（同日，Claude Science 用了两次后的建议）：结果解析成字段（items / facets / ai_summary / query_interpretation）·
#   Reaxys 每页调到最大 · 当天同一检索走缓存不扣次数 · chemdb_status（不碰网站）· SciFinder 筛选 / 排序 / 按原样搜 ·
#   SciFinder 按标题补 DOI、每条标 in_library / tier · Reaxys 预览拆成子检索列表 · AI 摘要没生成完标 complete=false
# v0.6（同日，用户：「最常用的是 CAS 号查精确结构、画大致结构查」）：structure（SMILES）+ match（exact / substructure /
#   similarity）走两个库的画图板；CAS 号 / 结构式回物质列表；CAS 号要文献时先落到物质再取它的文献

# 原样借用的（输出本来就合适）
BORROW = ()     # 2026-10-04 用户定：只给它做不到的（取全文）。数值库它自己会抽，不借了；ping 自己挂

MAX_DOIS = 25          # 一次提交的上限；与 getpdf 单次最多 25 篇的老约定一致
MAX_WAIT = 30          # fulltext_status 最多等多久（HTTP 服务一次只跑一个调用，等太久会堵别人）
STALE_SECS = 600       # 进度文件多久没动就当那个作业已经死了
STALL_SECS = 300       # 同一篇处理超过这么久没进展 → 状态里标 stalled（下载各步自带超时，正常到不了这么久）
CHEMDB_GAP = 30        # SciFinder / Reaxys 两次操作至少隔几秒（人的速度；不够就等，最多等这么久）
CHEMDB_DAILY = 20      # 每个库每天最多几次（搜索和翻页都算）；控制面板 CHEMDB_DAILY 可改
MAX_OUT = 50000        # 一次返回的结构化数据上限（字节）：调用方的远程命令输出过 64 KB 就被截断（2026-10 实测）

INSTRUCTIONS = """\
材料学研究者（聚硼硅氧烷 / 动态键弹性体）的文献证据库，约 1100 篇，跑在他校园网里的主力机上。
检索、读参考文献、抽数据你自己来；这里只给你做不到的：付费全文（学校订阅）取回并解析，以及他手上这些全文的查找、向量检索、按节读、看图。
每个工具都返回 structuredContent（JSON）；itemKey 可以给证据库 id，也可以直接给 DOI。
取全文：串行、每篇隔 20 秒、同时只跑一个作业（服务端强制，保护全校出口 IP），一篇约 1 分钟。
PDF 到手几秒内先出 tier=text（本地抽字，可按节读、无表格结构）；MineRU 后台补成 tier=structured（含表格）。
每篇结果带 code（OK / CAPTCHA_REQUIRED / NOT_SUBSCRIBED / NOT_FOUND / NO_PDF_LINK / PARSE_PENDING /
PARSE_FAILED / NETWORK_ERROR / NOT_FETCHED）与 retryable；CAPTCHA_REQUIRED 等人在主力机浏览器点完后用 fulltext_retry。
任何返回超过 50 KB 会写成文件、只回 spilled 路径。
文件路径是 B 机 WSL 路径（/mnt/d/...），你的 SSH 算力能直接读。
SciFinder / Reaxys：先 `chemdb_status`（不扣次数），再 `chemdb_search` 回第 1 页的结构化列表，`chemdb_page` 翻页。
按人的频率：两次至少隔 30 秒、每个库每天有上限（quota）；当天同一检索走缓存不扣次数 —— 先想好检索词，别试错式地连搜。
code=LOGIN_REQUIRED 时请人在主力机浏览器里登录。"""

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


MIN_HIT_CHARS = 80     # 比这短的命中多半只是一行小标题（"Molecular dynamics simulation"），没有可读的内容


def filter_hits(rows, n, per_paper=0, min_chars=MIN_HIT_CHARS):
    """去重 → 去掉只有一行标题的碎片 → 每篇最多 per_paper 段（0 = 不限）→ 取前 n。"""
    out, per = [], {}
    for r in dedupe_hits(rows):
        if len((r.get('text') or '').strip()) < min_chars:
            continue
        k = (r.get('doi') or r.get('id') or '').lower()
        if per_paper and per.get(k, 0) >= per_paper:
            continue
        per[k] = per.get(k, 0) + 1
        out.append(r)
        if len(out) >= n:
            break
    return out


def _retrieve(a):
    from tools import library
    n = int(a.get('n') or 8)
    per_paper = int(a.get('per_paper') or 0)
    # 多取一些候选：碎片和同篇超额的要筛掉（2026-10-04 Claude Science：滑环查询 5 条里 3 条同一篇）
    rows = library.retrieve(a['query'], n=n * (4 if per_paper else 2) + 4, where=a.get('where') or 'all')
    rows = filter_hits(rows, n, per_paper)
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
    data = {'itemKey': pid, 'available': True, 'main': slim(d), 'tier': F.tier_of(pid), 'rev': text_rev(pid),
            'cite_hint': '节号会随解析升级变（text → structured）；记出处请连 title 一起记，'
                         '取时传 title（或 quote 一句原文）就能找回，回复里有 remapped_from'}
    # 图注带上图片路径：整张图（full）优先，裁不出来的才给 MineRU 碎图（panel）；快速文本层没有图
    imgs = _figure_map(pid)
    for f in data['main']['figures']:
        f['image'], f['image_kind'] = imgs.get(_fig_key(f.get('ref')), ('', ''))
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
    """这篇「图号 → (图片 WSL 路径, 'full' | 'panel')」。

    先用按版面坐标裁好的**整张图**（`full_figures`）；裁不出来的号才退回 MineRU 的碎图（`panel`，
    多子图的 Figure 只指到其中一块 —— 2026-10-04 Claude Science 实测「图 1」只指到一个小图）。
    """
    from shared.kernel import paths
    out = {}
    md, img = paths.fulltext(pid), paths.images_dir(pid)
    if os.path.exists(md) and os.path.isdir(img):
        text = io.open(md, encoding='utf-8').read()
        out = {_fig_key(f['ref']): (to_wsl(f['image']), 'panel') for f in figure_images(text, img)}
    for f in full_figures(pid):
        if f.get('ref'):
            out[_fig_key(f['ref'])] = (to_wsl(f['image']), 'full')
    return out


_CAP_REF = re.compile(r'(?i)^\s*((?:fig(?:ure)?|scheme)\.?\s*S?\d+)')


def full_figures(pid, crop=None):
    """整张 Figure 的 PNG：[{num, page, ref, caption, image}]。裁一次存进 curated/<id>/figures/，之后直接读。

    要 MineRU 那一档（layout.json + 原 PDF）；快速文本层没有版面坐标，返回 []。
    layout.json 比索引新（重新解析过）就重裁。
    """
    import base64
    from shared.kernel import paths
    parsed = paths.parsed_dir(pid)
    lay = os.path.join(parsed, 'layout.json')
    if not os.path.exists(lay):
        return []
    d = paths.figures_dir(pid)
    idx = os.path.join(d, 'index.json')
    if os.path.exists(idx) and os.path.getmtime(idx) >= os.path.getmtime(lay):
        try:
            return json.load(io.open(idx, encoding='utf-8'))
        except ValueError:
            pass
    if crop is None:
        from shared.domain.figure_crop import crop_figures as crop
    try:
        figs = crop(parsed)
    except Exception:
        return []
    os.makedirs(d, exist_ok=True)
    out = []
    for f in figs:
        m = _CAP_REF.match(f.get('caption') or '')
        p = os.path.join(d, 'fig_%02d_p%d.png' % (f['num'], f['page'] + 1))
        io.open(p, 'wb').write(base64.b64decode(f['b64'].split(',', 1)[-1]))
        out.append({'num': f['num'], 'page': f['page'] + 1, 'ref': re.sub(r'\s+', ' ', m.group(1)) if m else '',
                    'caption': (f.get('caption') or '')[:200], 'image': p})
    io.open(idx, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False))
    return out


def text_rev(pid, si=False):
    """这篇正文（或 SI）当前版本的短指纹：档位 + 文本哈希前 8 位。变了就说明节号可能变了。"""
    import hashlib
    from shared.kernel import paths
    from tools.getpdf import fulltext as F
    p = paths.si_fulltext(pid) if si else paths.fulltext(pid)
    try:
        h = hashlib.sha1(io.open(p, 'rb').read()).hexdigest()[:8]
    except OSError:
        return ''
    return '%s-%s' % (F.tier_of(pid, si=si), h)


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
    si = bool(req.get('si'))
    addr, anchor = reanchor(pid, req.get('sectionId') or '', req.get('title') or '', req.get('quote') or '', si)
    r = library.section(pid, addr, max_chars=offset + max_chars, si=si)
    full = r.get('text', '')
    out = {'itemKey': pid, 'sectionId': addr, 'si': si, 'why_empty': r.get('why_empty', ''),
           'title': anchor.get('title', ''), 'rev': text_rev(pid, si)}
    if anchor.get('remapped_from'):
        out['remapped_from'] = anchor['remapped_from']
        out['remap_by'] = anchor['by']
    if anchor.get('warning'):
        out['warning'] = anchor['warning']
    if fmt in ('csv', 'json') and full:
        caption, rows = table_rows(full)
        if not caption and addr.lower().startswith('t'):
            caption = _table_caption(pid, addr, si)          # 表的文字只含 <table>，图注在骨架里
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


def _table_caption(pid, tid, si=False):
    from tools import library
    o = library.outline(pid)
    src = (o.get('si') or {}) if si else o
    for t in src.get('tables') or []:
        if t.get('id') == tid.lower():
            return t.get('caption') or ''
    return ''


def reanchor(pid, addr, title='', quote='', si=False):
    """按 title / quote 把（可能是旧版本的）地址对到现在的版本 → (地址, {title, remapped_from, by, warning})。

    - 给了 quote：以原句为准，找它现在所在的段 / 节（最精确）。
    - 给了 title：sectionId 那一节的标题对不上 → 按标题找回那一节（原来是段地址的，退到整节）。
    - 都没给：照 sectionId 取，只把那节现在的标题带回去，让调用方自己核。
    """
    from shared.domain.schema import outline as O
    from shared.kernel import paths
    from tools import library
    o = library.outline(pid)
    src = (o.get('si') or {}) if si else o
    titles = {x['id']: x.get('title', '') for x in src.get('sections') or []}
    sec = (addr or '').lower().partition('.')[0]
    info = {'title': titles.get(sec, '')}
    if not src.get('sections'):
        return addr, info
    if quote:
        p = paths.si_fulltext(pid) if si else paths.fulltext(pid)
        try:
            md = io.open(p, encoding='utf-8').read()
        except OSError:
            md = ''
        got = O.locate(md, src, quote)
        if got:
            if got.lower() != (addr or '').lower():
                info.update(remapped_from=addr, by='quote')
            info['title'] = titles.get(got.partition('.')[0], '')
            return got, info
        info['warning'] = '这句原文在当前版本里没找到（可能断行 / 公式写法不同）'
    if title and not addr:
        got = O.find_section(src, title)
        if got:
            info['title'] = titles.get(got, '')
            return got, info
        info['warning'] = '标题「%s」在当前版本里没找到' % title[:60]
    elif title and O.norm_text(titles.get(sec, '')) != O.norm_text(title):
        got = O.find_section(src, title)
        if got:
            info.update(remapped_from=addr, by='title', title=titles.get(got, ''))
            if '.' in (addr or ''):
                info['warning'] = '段号随版本变了，给的是整节'
            return got, info
        info['warning'] = '标题「%s」在当前版本里没找到，按 sectionId 照取' % title[:60]
    return addr, info


def _section(a):
    max_chars = int(a.get('maxChars') or 20000)
    reqs = a.get('requests') or ([{'itemKey': a.get('itemKey'), 'sectionId': a.get('sectionId'),
                                   'si': a.get('si'), 'title': a.get('title'), 'quote': a.get('quote')}]
                                 if a.get('itemKey') else [])
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


MAX_IMAGE_KB = 36      # base64 会大三分之一，36 KB 的图回出去约 48 KB，压在 50 KB 线内


def _figure_image(a):
    """一张图直接回成小 JPEG（base64）：不用传文件、不用等界面批准（2026-10-04 Claude Science：取一张图等了 20 多分钟）。"""
    import base64
    from shared.domain.figure_crop import shrink_jpeg
    pid = _resolve(a.get('itemKey'))
    want = str(a.get('fig') or '').strip()
    key = _fig_key('figure ' + want if want.isdigit() else want)
    imgs = _figure_map(pid)
    hit = imgs.get(key)
    if not hit:
        raise ValueError('「%s」没有对上的图片；有的是：%s' % (want, ', '.join(sorted(imgs)) or '（这篇还没有图片，tier 不是 structured）'))
    path, kind = hit
    win = path
    if win.startswith('/mnt/'):
        win = win[5].upper() + ':' + win[6:].replace('/', os.sep)
    max_kb = max(8, min(int(a.get('max_kb') or 30), MAX_IMAGE_KB))
    data = shrink_jpeg(win, max_kb * 1024)
    if not data:
        raise ValueError('这张图缩不到 %d KB 以内（或读不了）：%s' % (max_kb, path))
    return _out('%s %s：%d KB JPEG（%s）' % (pid, want, len(data) // 1024, '整张图' if kind == 'full' else '子图碎块'),
                {'itemKey': pid, 'fig': want, 'image_kind': kind, 'path': path, 'mime': 'image/jpeg',
                 'bytes': len(data), 'base64': base64.b64encode(data).decode()})


def _paper_files(a):
    pid = _resolve(a.get('itemKey'))
    got = paper_files(pid)
    data = {'itemKey': pid, 'files': {k: to_wsl(p) for k, p in got.items()}, 'figures': []}
    m = _figure_map(pid)
    data['figures'] = [{'ref': k.title(), 'image': v[0], 'image_kind': v[1]} for k, v in sorted(
        m.items(), key=lambda kv: (kv[0].split(' ')[0], int(re.sub(r'\D', '', kv[0]) or 0)))]
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



# ══════════════════════════════════════════════════════════════════════
# SciFinder / Reaxys：按人的频率搜、读结果页（2026-10-08）
# ══════════════════════════════════════════════════════════════════════

def _chemdb_usage_path():
    from shared.kernel import paths
    return paths.runtime('chemdb_usage.json')


def _load(path):
    try:
        return json.load(io.open(path, encoding='utf-8'))
    except Exception:
        return {}


def _day(now):
    return time.strftime('%Y-%m-%d', time.localtime(now))


def chemdb_daily():
    from shared.kernel import config
    try:
        return int(config.get_key('CHEMDB_DAILY', default='') or CHEMDB_DAILY)
    except ValueError:
        return CHEMDB_DAILY


def chemdb_quota(db, path=None, now=None, daily=None):
    """→ (今天已用, 上限, 还要等几秒)。账本按天记，跨天自动清零。"""
    now = now or time.time()
    d = _load(path or _chemdb_usage_path())
    daily = chemdb_daily() if daily is None else daily
    used = d.get('days', {}).get(_day(now), {}).get(db, 0)
    wait = max(0.0, CHEMDB_GAP - (now - float(d.get('last', 0))))
    return used, daily, wait


def chemdb_charge(db, path=None, now=None, last_search=None):
    """记一次（搜索或翻页）。只留最近 7 天。last_search = 这个库最近一次搜索的参数 + 列表网址（翻页要用）。"""
    now = now or time.time()
    path = path or _chemdb_usage_path()
    d = _load(path)
    today = _day(now)
    days = d.get('days', {})
    days.setdefault(today, {})[db] = days.get(today, {}).get(db, 0) + 1
    out = {'last': now, 'days': {k: days[k] for k in sorted(days)[-7:]}, 'searches': d.get('searches', {})}
    if last_search is not None:
        out['searches'][db] = last_search
    io.open(path, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False))


def _remember_search(db, search, path=None):
    """缓存命中时也要记住「这个库现在的检索是哪次」，翻页才翻得对。不扣次数。"""
    path = path or _chemdb_usage_path()
    d = _load(path)
    d.setdefault('searches', {})[db] = search
    io.open(path, 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False))


def chemdb_key(db, params, page):
    """同一库、同一检索（词 + 类 + 排序 + 筛选 + 模式）、同一页 → 同一个缓存键。"""
    import hashlib
    sig = json.dumps({'db': db, 'p': {k: params.get(k) for k in ('query', 'kind', 'sort', 'filters', 'mode', 'structure', 'match')},
                      'page': int(page), 'v': VERSION}, sort_keys=True, ensure_ascii=False)   # 升版本 = 解析变了，旧缓存作废
    return hashlib.sha1(sig.encode('utf-8')).hexdigest()[:16]


def _cache_path(key, now=None, root=None):
    from shared.kernel import paths
    root = root or paths.runtime('chemdb_cache')
    return os.path.join(root, _day(now or time.time()), key + '.json')


def cache_get(key, now=None, root=None):
    p = _cache_path(key, now, root)
    return (_load(p) or None) if os.path.exists(p) else None


def cache_put(key, r, now=None, root=None):
    import shutil
    p = _cache_path(key, now, root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    io.open(p, 'w', encoding='utf-8').write(json.dumps(r, ensure_ascii=False))
    base = os.path.dirname(os.path.dirname(p))
    for old in sorted(os.listdir(base))[:-3]:          # 缓存只留最近 3 天
        shutil.rmtree(os.path.join(base, old), ignore_errors=True)


DOI_SURE = 0.9          # 标题相似度到这个数，就当是它
DOI_MAYBE = 0.75        # 到这个数，给 DOI 但标 doi_uncertain，让调用方自己判


def enrich(items, match=None, find=None, tier=None, warnings=None):
    """补 DOI（SciFinder 列表没有，按标题去 Crossref 找）+ 标出证据库里有没有、能读到哪一档。"""
    warnings = [] if warnings is None else warnings
    if match is None:
        from shared.adapters import crossref

        def _crossref(it):
            first = ((it.get('authors') or [''])[0] or '').split(',')[0]
            return crossref.match_title(it['title'], it.get('year'), first)
        match = _crossref
    if find is None or tier is None:
        from shared.kernel import catalog
        from tools.getpdf import fulltext as F
        find, tier = find or catalog.find, tier or F.tier_of
    todo = [it for it in items if not it.get('doi') and it.get('type') not in ('patent', 'substance') and it.get('title')]
    if todo:
        from concurrent.futures import ThreadPoolExecutor

        def _m(it):
            for attempt in range(3):          # 2026-10-08：5 路并发被 Crossref 限流，42 条只配上 16 条
                try:
                    return True, match(it)
                except Exception:
                    time.sleep(1.5 * (attempt + 1))
            return False, None
        with ThreadPoolExecutor(max_workers=2) as ex:
            got_all = list(ex.map(_m, todo))
        failed = sum(1 for ok, _ in got_all if not ok)
        if failed:
            warnings.append(f'doi_lookup_failed: {failed} 条按标题去 Crossref 查 DOI 没查成（网络 / 限流），可以自己按标题再找')
        for it, (_, got) in zip(todo, got_all):
            if got and got.get('doi') and got['score'] >= DOI_MAYBE:
                it['doi'] = got['doi']
                it['doi_source'] = 'crossref_title_match'
                it['doi_match_score'] = got['score']
                if got['score'] < DOI_SURE:
                    it['doi_uncertain'] = True
    for it in items:
        if it.get('doi'):
            pid = find(it['doi'])
            it['in_library'] = bool(pid)
            if pid:
                it['id'] = pid
                try:
                    it['tier'] = tier(pid)
                except Exception:
                    it['tier'] = None
        elif it.get('type') not in ('patent', 'substance'):
            it['in_library'] = None
    return items


def _deliver(r, db, params, cached):
    r = dict(r)
    used, daily, _ = chemdb_quota(db)
    r['cached'] = cached
    r['quota'] = {'used_today': used, 'daily_limit': daily, 'remaining': max(0, daily - used),
                  'min_gap_s': CHEMDB_GAP}
    if not params.get('raw'):
        r.pop('text', None)
    n = len(r.get('items') or [])
    head = '%s %s%s：%s' % (db, r.get('code'), '（缓存）' if cached else '',
                            r.get('why') or '共 %s 条，第 %s 页 %d 条' % (r.get('count'), r.get('page'), n))
    return _out(head, r)


def _chemdb_run(db, params, page, fetch):
    """缓存 → 额度 → 间隔 → 去网站 → 补 DOI 与库内标记 → 存缓存。"""
    from shared.adapters import chemdb
    db = chemdb.check_db(db)
    key = chemdb_key(db, params, page)
    hit = cache_get(key)
    if hit:
        if page == 1:
            _remember_search(db, dict(params, url=hit.get('url')))
        return _deliver(hit, db, params, True)
    used, daily, wait = chemdb_quota(db)
    if used >= daily:
        raise ValueError(f'{db} 今天已经用了 {used} 次（上限 {daily}，按人的频率）；明天再来，'
                         f'或请用户在控制面板调 CHEMDB_DAILY。当天查过的检索照样能从缓存拿（不扣次数）')
    if wait:
        time.sleep(wait)                      # 不到 30 秒就等够再做（人的节奏），不让调用方白跑一趟
    r = fetch(db)
    keep = {k: v for k, v in params.items() if k != 'raw'}
    chemdb_charge(db, last_search=dict(keep, url=r.get('url')) if page == 1 and r.get('url') else None)
    if r.get('items'):
        try:
            enrich(r['items'], warnings=r.setdefault('warnings', []))
        except Exception as e:
            r.setdefault('warnings', []).append(f'enrich_failed: {type(e).__name__}: {str(e)[:80]}')
    if r.get('code') in ('OK', 'NO_RESULTS') and r.get('complete', True):
        cache_put(key, r)
    return _deliver(r, db, params, False)


def _chemdb_params(a):
    return {'query': (a.get('query') or '').strip(), 'kind': a.get('kind') or 'references',
            'sort': a.get('sort') or None, 'filters': a.get('filters') or None,
            'mode': a.get('mode') or 'auto', 'raw': bool(a.get('raw')),
            'structure': (a.get('structure') or '').strip() or None,
            'match': (a.get('match') or 'exact') if a.get('structure') else None}


def _chemdb_search(a):
    from shared.adapters import chemdb
    p = _chemdb_params(a)
    mc = int(a.get('maxChars') or 30000)
    return _chemdb_run(a.get('db'), p, 1, lambda db: chemdb.search(
        db, p['query'], p['kind'], structure=p['structure'] or '', match=p['match'] or 'exact', sort=p['sort'],
        filters=p['filters'], mode=p['mode'], raw=p['raw'], max_chars=mc))


def _chemdb_page(a):
    from shared.adapters import chemdb
    db = chemdb.check_db(a.get('db'))
    n = int(a.get('page') or 2)
    last = (_load(_chemdb_usage_path()).get('searches') or {}).get(db)
    if not last:
        raise ValueError(f'{db} 还没有搜过（或账本被清了），先 chemdb_search')
    p = dict(last, raw=bool(a.get('raw')))
    mc = int(a.get('maxChars') or 30000)
    return _chemdb_run(db, p, n, lambda db: chemdb.page(db, n, base_url=last.get('url') or '', raw=p['raw'],
                                                       max_chars=mc))


def _chemdb_status(a):
    """不碰网站：额度、几点重置、两个库最近一次检索、标签停在哪（登录页 = 要人去登录）、导出文件夹里有什么。"""
    from shared.adapters import chemdb
    from shared.kernel import paths
    now = time.time()
    d = _load(_chemdb_usage_path())
    t = time.localtime(now)
    reset = time.mktime((t.tm_year, t.tm_mon, t.tm_mday + 1, 0, 0, 0, 0, 0, -1))
    out = {'quota': {}, 'reset_at': time.strftime('%Y-%m-%d %H:%M', time.localtime(reset)),
           'min_gap_s': CHEMDB_GAP, 'last_searches': d.get('searches') or {}}
    for db in chemdb.DBS:
        used, daily, _ = chemdb_quota(db, now=now)
        out['quota'][db] = {'used_today': used, 'daily_limit': daily, 'remaining': max(0, daily - used)}
    out['wait_s'] = round(chemdb_quota('scifinder', now=now)[2], 1)
    try:
        tabs = chemdb.tabs()
        for st in tabs.values():
            st['login'] = 'login_page' if st['login_page'] else ('likely_ok' if st['tab_open'] else 'unknown')
        out['tabs'] = tabs
    except Exception as e:
        out['tabs'] = {'error': f'{type(e).__name__}: {str(e)[:160]}'}
    ex = paths.CHEMDB_EXPORTS
    files = sorted(os.listdir(ex)) if os.path.isdir(ex) else []
    out['exports'] = {'dir': to_wsl(ex), 'files': files[-50:],
                      'hint': '用户手动从 SciFinder / Reaxys 导出的 Excel / RIS 放这里；你直接读（不扣次数）'}
    q = out['quota']
    return _out('SciFinder 今天还剩 %d 次、Reaxys 还剩 %d 次；%s 重置' % (
        q['scifinder']['remaining'], q['reaxys']['remaining'], out['reset_at']), out)


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
    ('library_retrieve', '向量检索证据库：最相近的段落 + 文献 id + 节地址（拿去 library_section 读上下文）。'
     '只有一行标题的碎片已滤掉；per_paper=1 每篇最多一段。',
     {'query': {'type': 'string'}, 'n': {'type': 'integer', 'minimum': 1, 'maximum': 30},
      'per_paper': {'type': 'integer', 'minimum': 0, 'maximum': 10},
      'where': {'type': 'string', 'enum': ['all', 'main', 'si']}}, ['query'], _retrieve),
    ('library_outline', '一篇的骨架：节 / 长节的段 / 表 / 图注，各自的地址、类别、字数。有 SI 的另给 si 一份。',
     {'itemKey': _KEY}, ['itemKey'], _outline),
    ('library_section', '按地址取原文：s5 一节（含子节）/ s5.p3 一段 / t1 一张表 / f2 一条图注；SI 的传 si=true。'
     '表格 format=csv|json（默认 html）。长的用 offset 分页（回 next_offset）。'
     '节号会随解析升级变：传 title（节标题）或 quote（一句原文）找回现在的位置，回复带 remapped_from。'
     '可批量：requests=[{itemKey, sectionId, title, quote, si, offset, format}]（最多 50 处）。',
     {'itemKey': _KEY, 'sectionId': {'type': 'string'}, 'si': {'type': 'boolean'},
      'requests': {'type': 'array', 'items': {'type': 'object'}},
      'offset': {'type': 'integer', 'minimum': 0},
      'title': {'type': 'string'}, 'quote': {'type': 'string'},
      'format': {'type': 'string', 'enum': ['html', 'csv', 'json']},
      'maxChars': {'type': 'integer', 'minimum': 100, 'maximum': 200000}}, [], _section),
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
    ('figure_image', '一张图直接回成小 JPEG（base64，默认 ≤30 KB，最多 36 KB）：fig 给 "Figure 2" / "Scheme 1" / "2"。'
     '不用传文件。整张图（image_kind=full）要 tier=structured。',
     {'itemKey': _KEY, 'fig': {'type': 'string'}, 'max_kb': {'type': 'integer', 'minimum': 8, 'maximum': MAX_IMAGE_KB}},
     ['itemKey', 'fig'], _figure_image),
    ('fulltext_retry', '续跑：把上一个作业里撞人机验证 / 暂缓 / 网络错的再交一次（人在主力机浏览器点完验证后用）。'
     '也可以自己给 dois。规矩同 paper_fulltext。',
     {'dois': {'type': 'array', 'items': {'type': 'string'}}}, [], _retry),
    ('paper_status', '一批 DOI 或 id 的现状：在不在库、tier（none/text/structured）、SI、节 / 表 / 图数、'
     '上次取全文的 route 与错误码。零成本，不取不解析。',
     {'dois': {'type': 'array', 'items': {'type': 'string'}},
      'itemKeys': {'type': 'array', 'items': {'type': 'string'}}}, [], _paper_status),
    ('chemdb_search', '在 SciFinder 或 Reaxys 里搜一次（借主力机上已登录的浏览器），回第 1 页的结构化列表。'
     '三种入口：关键词（query）、CAS 号（query="98-80-6"）、结构式（structure=SMILES + match=exact|substructure|similarity）。'
     'CAS 号或结构式 + kind=substances → 物质列表（cas_rn / formula / name / 被多少文献、反应用到）；'
     'CAS 号 + kind=references → 先落到这个物质再取用了它的文献 / 专利（warnings 里有 via_substance）。文献列表：'
     'items[]（rank / type=journal|review|patent / title / authors / source / year / doi / patent_no / assignee / status / '
     'cited|citing / snippet / index_terms / in_library / tier）、count、page_size、pages、facets（SciFinder 带计数）、'
     'query_interpretation（库实际执行的检索式）、ai_summary、Reaxys 的 preview（整句拆成的子检索及各自条数）、complete、warnings。'
     'SciFinder 列表没有 DOI，服务端按标题去 Crossref 补（doi_match_score；<0.9 标 doi_uncertain）。'
     '当天同一检索同一页走缓存（cached=true，不扣次数）。不在缓存时：两次至少隔 30 秒（服务端会等），每库每天有上限（quota）。',
     {'db': {'type': 'string', 'enum': ['scifinder', 'reaxys'], 'description': '哪个库'},
      'query': {'type': 'string', 'description': '检索词（英文）或 CAS 号。SciFinder 会把词用 and 连起来，看 query_interpretation。'
                '和 structure 一起给 = 结构 + 关键词同时满足'},
      'structure': {'type': 'string', 'description': '结构式：SMILES（Reaxys 也收 molfile）。两个库的搜索框都不认 SMILES，服务端走它们的画图板'},
      'match': {'type': 'string', 'enum': ['exact', 'substructure', 'similarity'],
                'description': '结构怎么比：exact = 按原样（含同位素、盐等变体）/ substructure = 含这个骨架 / similarity = 相似；默认 exact'},
      'kind': {'type': 'string', 'enum': ['references', 'substances', 'reactions'],
               'description': 'references = 文献 + 专利（默认）；substances = 物质列表；reactions 目前只回原样文字（用 raw=true）'},
      'sort': {'type': 'string', 'enum': ['relevance', 'date', 'cited'], 'description': '排序，默认 relevance'},
      'filters': {'type': 'object', 'description': '只 SciFinder：{facet 名: [值]}，名与值照 facets 里写（如 '
                  '{"Document Type": ["Journal"], "Patent Status": ["Alive"]}），另认 yearFrom / yearTo（整数年）。'
                  '只有页面左侧显示出来的值能选（每个 facet 前 5 个），选不到会进 warnings'},
      'mode': {'type': 'string', 'enum': ['auto', 'original'],
               'description': 'original = SciFinder 改写了检索式时按原样搜（点 Search Original Query）'},
      'raw': {'type': 'boolean', 'description': '另附整页原文 text（排查用，平时别开）'},
      'maxChars': {'type': 'integer', 'minimum': 1000, 'maximum': 45000, 'description': 'raw 原文的上限'}},
     ['db'], _chemdb_search),
    ('chemdb_page', '这个库最近一次 chemdb_search 的第 page 页（同样的结构化字段；同一页当天走缓存）。额度与间隔规矩同上。',
     {'db': {'type': 'string', 'enum': ['scifinder', 'reaxys']},
      'page': {'type': 'integer', 'minimum': 1, 'description': '页码；pages 告诉你一共几页'},
      'raw': {'type': 'boolean'}, 'maxChars': {'type': 'integer', 'minimum': 1000, 'maximum': 45000}},
     ['db', 'page'], _chemdb_page),
    ('chemdb_status', '不碰网站、不扣次数：两个库今天各剩几次、几点重置、要等几秒、最近一次检索（词 + 网址）、'
     '浏览器标签停在哪（login=login_page 就是要人去登录）、人手动导出文件的文件夹和里面的文件。做一组检索之前先看它。',
     {}, [], _chemdb_status),
]


def _ping(a):
    return _out(f'{NAME} {VERSION} 在跑', {'ok': True, 'server': NAME, 'version': VERSION})


def build(full):
    """装成给 Claude Science 的服务：只挂它做不到的那几样（取全文 + 读取回来的全文）。每个都套 50 KB 上限。"""
    s = MCPStdioServer(NAME, VERSION, instructions=INSTRUCTIONS)
    s.register_tool('ping', '存活检查：服务在跑、是哪一版。', {'type': 'object', 'properties': {}}, _ping)
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
