# -*- coding: utf-8 -*-
"""journalwatch · 盯新刊：好期刊一出新文章就列出来（2026-09-15 建）

**解决的真实问题**：用户想要「这些好刊一发相关方向的新论文，系统就知道、就取下来」。
期刊官网的邮件提醒是给人看的，程序读邮件既绕又脆；更干净的路是直接问 DOI 登记处 ——
出版社注册 DOI 的那一刻 Crossref 就有了，按「这本刊 + 这天之后」列，不要账号不要钱。

**做的是「0 级」：列出来、标出库里有没有、存进雷达库**（`store.py`，题目 / 摘要 / 参考文献 DOI，
一篇 4 KB）。相关度筛选与自动取件是后面的事，要等用户看过几周清单、把「要 / 不要」的线画准了再开
（取件是最脆弱的一环，宁少勿滥）。`backfill(years=3)` 把过去几年的也拉进雷达（同一套代码，窗口拉长）。

用法：
    from tools import journalwatch
    items = journalwatch.patrol(days=7)          # 每本刊最近 7 天新登记的正式论文
    # item: {title, doi, venue, published, created, abstract, first_author,
    #        in_library(证据库里已有的 id 或 ''), is_new(这次首见)}

盯哪些刊：`paths.journal_watch()`（用户编辑；没有就用 DEFAULT_JOURNALS 建一份）。
见过哪些：`paths.journal_watch_seen()`（state，可删）。

依赖：shared.adapters.crossref（联网）、shared.kernel.catalog / paths（本地）。
"""
import datetime as _dt
import io
import json
import os

from shared.adapters import crossref, openalex
from shared.kernel import catalog, heartbeat, paths
from shared.kernel.log import get_logger
from tools.journalwatch import store

_log = get_logger('journalwatch')

# 种子清单（2026-09-16 按证据库里 987 篇的真实出处 + 用户定的三档框架重拟；ISSN 全部在 Crossref
# `/journals/<ISSN>` 上逐个验过，不是凭记忆写的）。用户改 `journal_watch.json` 就行，这里只在文件不存在时用一次。
#
# 三档回答的问题不一样（docs/变更记录 2026-09-16）：
#   A 方向层：行业往哪走、新概念第一次出现在哪 —— 综合刊 + 化学/材料顶刊
#   B 领域层：这个体系具体怎么做、参数在哪 —— 高分子 / 软物质专刊，实验细节密度最高
#   C 宽口层：口宽、量大、噪音最大 —— 只取被相关度筛出来的
# 档位是每篇的属性，不是收不收的闸门；闸门是相关度（引了库内几篇 + 相似度），门槛按档位不同（TIER_GATE）。
DEFAULT_JOURNALS = [
    # ── A 方向层 ──
    {'name': 'Nature', 'issn': '0028-0836', 'tier': 'A'},
    {'name': 'Science', 'issn': '0036-8075', 'tier': 'A'},
    {'name': 'Nature Materials', 'issn': '1476-1122', 'tier': 'A'},
    {'name': 'Nature Chemistry', 'issn': '1755-4330', 'tier': 'A'},
    {'name': 'Nature Nanotechnology', 'issn': '1748-3387', 'tier': 'A'},
    {'name': 'Nature Sustainability', 'issn': '2398-9629', 'tier': 'A'},
    {'name': 'Nature Reviews Materials', 'issn': '2058-8437', 'tier': 'A'},
    {'name': 'Nature Communications', 'issn': '2041-1723', 'tier': 'A'},
    {'name': 'Science Advances', 'issn': '2375-2548', 'tier': 'A'},
    {'name': 'Proceedings of the National Academy of Sciences', 'issn': '0027-8424', 'tier': 'A'},
    {'name': 'National Science Review', 'issn': '2095-5138', 'tier': 'A'},
    {'name': 'Matter', 'issn': '2590-2385', 'tier': 'A'},
    {'name': 'Chem', 'issn': '2451-9294', 'tier': 'A'},
    {'name': 'Journal of the American Chemical Society', 'issn': '0002-7863', 'tier': 'A'},
    {'name': 'Angewandte Chemie International Edition', 'issn': '1433-7851', 'tier': 'A'},
    {'name': 'Advanced Materials', 'issn': '0935-9648', 'tier': 'A'},
    {'name': 'Advanced Functional Materials', 'issn': '1616-301X', 'tier': 'A'},
    {'name': 'ACS Nano', 'issn': '1936-0851', 'tier': 'A'},
    {'name': 'ACS Central Science', 'issn': '2374-7943', 'tier': 'A'},
    {'name': 'Chemical Reviews', 'issn': '0009-2665', 'tier': 'A'},
    {'name': 'Chemical Society Reviews', 'issn': '0306-0012', 'tier': 'A'},
    {'name': 'Accounts of Chemical Research', 'issn': '0001-4842', 'tier': 'A'},
    {'name': 'Materials Today', 'issn': '1369-7021', 'tier': 'A'},
    {'name': 'Materials Science and Engineering: R: Reports', 'issn': '0927-796X', 'tier': 'A'},
    # ── B 领域层 ──
    {'name': 'Macromolecules', 'issn': '0024-9297', 'tier': 'B'},
    {'name': 'ACS Macro Letters', 'issn': '2161-1653', 'tier': 'B'},
    {'name': 'Polymer Chemistry', 'issn': '1759-9954', 'tier': 'B'},
    {'name': 'Progress in Polymer Science', 'issn': '0079-6700', 'tier': 'B'},
    {'name': 'Chemistry of Materials', 'issn': '0897-4756', 'tier': 'B'},
    {'name': 'Materials Horizons', 'issn': '2051-6347', 'tier': 'B'},
    {'name': 'Polymer', 'issn': '0032-3861', 'tier': 'B'},
    {'name': 'ACS Applied Polymer Materials', 'issn': '2637-6105', 'tier': 'B'},
    {'name': 'Biomacromolecules', 'issn': '1525-7797', 'tier': 'B'},
    {'name': 'Soft Matter', 'issn': '1744-683X', 'tier': 'B'},
    {'name': 'Journal of Polymer Science', 'issn': '2642-4169', 'tier': 'B'},
    {'name': 'European Polymer Journal', 'issn': '0014-3057', 'tier': 'B'},
    {'name': 'Macromolecular Rapid Communications', 'issn': '1022-1336', 'tier': 'B'},
    {'name': 'Macromolecular Materials and Engineering', 'issn': '1438-7492', 'tier': 'B'},
    {'name': 'Macromolecular Chemistry and Physics', 'issn': '1022-1352', 'tier': 'B'},
    {'name': 'Chinese Journal of Polymer Science', 'issn': '0256-7679', 'tier': 'B'},
    {'name': 'Polymer Degradation and Stability', 'issn': '0141-3910', 'tier': 'B'},
    {'name': 'Composites Science and Technology', 'issn': '0266-3538', 'tier': 'B'},
    {'name': 'Composites Part B: Engineering', 'issn': '1359-8368', 'tier': 'B'},
    {'name': 'ACS Materials Letters', 'issn': '2639-4979', 'tier': 'B'},
    {'name': 'Accounts of Materials Research', 'issn': '2643-6728', 'tier': 'B'},
    {'name': 'Advanced Fiber Materials', 'issn': '2524-7921', 'tier': 'B'},
    {'name': 'Nano-Micro Letters', 'issn': '2311-6706', 'tier': 'B'},
    # ── C 宽口层 ──
    {'name': 'Chemical Engineering Journal', 'issn': '1385-8947', 'tier': 'C'},
    {'name': 'ACS Applied Materials & Interfaces', 'issn': '1944-8244', 'tier': 'C'},
    {'name': 'Small', 'issn': '1613-6810', 'tier': 'C'},
    {'name': 'Advanced Science', 'issn': '2198-3844', 'tier': 'C'},
    {'name': 'Journal of Materials Chemistry A', 'issn': '2050-7488', 'tier': 'C'},
    {'name': 'Nano Letters', 'issn': '1530-6984', 'tier': 'C'},
    {'name': 'Nano Energy', 'issn': '2211-2855', 'tier': 'C'},
    {'name': 'Green Chemistry', 'issn': '1463-9262', 'tier': 'C'},
    {'name': 'ACS Sustainable Chemistry & Engineering', 'issn': '2168-0485', 'tier': 'C'},
    {'name': 'Industrial & Engineering Chemistry Research', 'issn': '0888-5885', 'tier': 'C'},
    {'name': 'Chemical Communications', 'issn': '1359-7345', 'tier': 'C'},
    {'name': 'Science China Materials', 'issn': '2095-8226', 'tier': 'C'},
]

# 升 1 级（取正文 + 解析）的门槛：这篇引了证据库里几篇。B 松、A 中、C 紧。
# 数字是起点，看几周清单再调；相似度那一路（向量）接上后再并进来。
TIER_GATE = {'A': 2, 'B': 1, 'C': 3}

MAX_DAYS = 60          # 窗口再大 Crossref 一页也装不下，且「新刊」本来就只看最近


def load_journals(path=None):
    """盯着的刊物清单 → [{'name', 'issn'}]。文件不存在就用种子建一份（只建这一次）。"""
    path = path or paths.journal_watch()
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        io.open(path, 'w', encoding='utf-8').write(json.dumps(
            {'note': '盯新刊的清单。加刊：写 name 和 ISSN（任一个 ISSN 都行，纸质/电子不分）。'
                     '暂时不想盯的加 "off": true。',
             'journals': DEFAULT_JOURNALS}, ensure_ascii=False, indent=1))
    d = json.loads(io.open(path, encoding='utf-8').read())
    return [dict(j, tier=(j.get('tier') or 'C').upper())
            for j in d.get('journals', []) if j.get('issn') and not j.get('off')]


def load_seen(path=None):
    path = path or paths.journal_watch_seen()
    try:
        return json.loads(io.open(path, encoding='utf-8').read())
    except Exception:
        return {'dois': {}, 'checked': {}}


def save_seen(seen, path=None):
    path = path or paths.journal_watch_seen()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io.open(path, 'w', encoding='utf-8').write(json.dumps(seen, ensure_ascii=False, indent=0))


def _since(days, today=None):
    today = today or _dt.date.today()
    return (today - _dt.timedelta(days=max(1, min(int(days), MAX_DAYS)))).isoformat()


def fetch(journals, days=7, log=None, today=None):
    """逐刊问 Crossref → 平铺的新文章列表（不碰本地状态，纯取）。一本刊挂了只记一笔，继续。"""
    log = log or _log.info
    since = _since(days, today)
    out, failed = [], []
    for j in journals:
        try:
            ws = crossref.journal_works_since(j['issn'], since)
        except crossref.CrossrefError as e:
            failed.append(j['name'])
            log('  %s 没查成：%s' % (j['name'], str(e)[:60]))
            continue
        for w in ws:
            w['venue'] = j['name'] or w['venue']     # 用清单里的名字，Crossref 的偶尔带副标题
            w['tier'] = j.get('tier', 'C')
        out.extend(ws)
        log('  %-42s %3d 篇（%s 起）' % (j['name'], len(ws), since))
    return out, failed


def annotate(items, seen, today=None):
    """给每篇标：`in_library`（证据库 id 或 ''）、`is_new`（这次首见）。**会改 seen**（记首见日）。"""
    today = (today or _dt.date.today()).isoformat()
    dois = seen.setdefault('dois', {})
    lib = catalog.by_doi()                # 扫一次；`catalog.find` 每调一次都重扫全库，几百篇一起问会卡死（踩坑 #161）
    out, have = [], set()
    for w in items:
        d = catalog.norm_doi(w['doi'])
        if not d or d in have:
            continue                      # 同一篇在两个 ISSN 下各出现一次
        have.add(d)
        w['in_library'] = lib.get(d, '')
        w['is_new'] = d not in dois
        # 相关度第一道线：它引了证据库里几篇（参考文献 DOI 对证据库 DOI 表）
        w['lib_cites'] = sum(1 for r in (w.get('refs') or []) if r in lib)
        w['passes'] = w['lib_cites'] >= TIER_GATE.get(w.get('tier', 'C'), 3)
        dois.setdefault(d, today)
        out.append(w)
    out.sort(key=lambda w: (w['venue'], w['created'] or '', w['title']), reverse=False)
    return out


def patrol(days=7, journals=None, log=None, only_new=False, today=None, remember=True):
    """一次巡逻：取 → 标注 → 记住见过的 → 返回列表。

    only_new=True 只返回这次首见的（定时跑用）；默认全返回，`is_new` 字段区分。
    remember=False 不写 seen 文件（测试 / 只看看）。
    """
    log = log or _log.info
    journals = journals if journals is not None else load_journals()
    seen = load_seen()
    items, failed = fetch(journals, days=days, log=log, today=today)
    rows = annotate(items, seen, today=today)
    if remember:
        for j in journals:
            if j['name'] not in failed:
                seen.setdefault('checked', {})[j['issn']] = (today or _dt.date.today()).isoformat()
        save_seen(seen)
        con = store.connect()
        try:
            store.upsert(con, rows, today=today)
        finally:
            con.close()
        try:
            refresh(log=lambda *a: None)
        except Exception:
            pass
    if only_new:
        rows = [w for w in rows if w['is_new']]
    return {'items': rows, 'failed': failed, 'since': _since(days, today),
            'n_journals': len(journals)}


def backfill(years=3, journals=None, log=None, until=None, progress=None):
    """把过去几年的正式论文拉进雷达库（0 级：题目 / 摘要 / 作者 / 参考文献 DOI）。

    每本刊按出版日按年切块翻页（一块最多几千条，cursor 翻页），做完一块就写库、记进度
    （`progress` 文件），中断了下次从没做完的块接着 —— 25 万条要跑一晚上，不能一断全重来。
    返回 {'works': 新增篇数, 'chunks': 做了几块, 'failed': [刊名]}。
    """
    log = log or _log.info
    journals = journals if journals is not None else load_journals()
    until = until or _dt.date.today()
    since = until.replace(year=until.year - int(years))
    progress = progress or (paths.journal_watch_seen() + '.backfill')
    try:
        done = set(json.loads(io.open(progress, encoding='utf-8').read()))
    except Exception:
        done = set()
    con = store.connect()
    lib = catalog.by_doi()                # 同上：扫一次，别每篇重扫
    total_new, chunks, failed = 0, 0, []
    try:
        for j in journals:
            a = since
            while a < until:
                b = min(a.replace(year=a.year + 1), until)
                key = '%s|%s|%s' % (j['issn'], a, b)
                if key in done:
                    a = b
                    continue
                flt = 'from-pub-date:%s,until-pub-date:%s,type:journal-article' % (a, b)
                cursor, got, n_new = '*', 0, 0
                try:
                    while cursor:
                        items, cursor, total = crossref.journal_works(j['issn'], flt, cursor=cursor)
                        for w in items:
                            w['in_library'] = lib.get(catalog.norm_doi(w['doi']), '')
                            w['venue'] = j['name'] or w['venue']      # Crossref 的刊名偶尔带换行 / 副标题
                            w['tier'] = j.get('tier', 'C')
                            w['lib_cites'] = sum(1 for r in (w.get('refs') or []) if r in lib)
                        n_new += store.upsert(con, items)
                        got += len(items)
                except crossref.CrossrefError as e:
                    failed.append(j['name'])
                    log('  %s %s~%s 没拉完（拿到 %d）：%s' % (j['name'], a, b, got, str(e)[:60]))
                    break
                done.add(key)
                io.open(progress, 'w', encoding='utf-8').write(json.dumps(sorted(done)))
                heartbeat.progress('journalwatch-backfill')
                total_new += n_new
                chunks += 1
                log('  %-40s %s~%s  %5d 篇（新 %d）' % (j['name'], a, b, got, n_new))
                a = b
    finally:
        con.close()
    heartbeat.done('journalwatch-backfill')
    return {'works': total_new, 'chunks': chunks, 'failed': sorted(set(failed))}


def refresh(log=None):
    """证据库长了之后重算雷达里的「引了库内几篇」与档位（回填完、每天巡逻后各跑一次，几秒钟）。"""
    log = log or _log.info
    con = store.connect()
    try:
        lib = catalog.by_doi()
        n = store.refresh_lib_cites(con, list(lib), {j['name']: j['tier'] for j in load_journals()})
        m = store.refresh_library_flags(con, lambda d: lib.get(catalog.norm_doi(d), ''))
    finally:
        con.close()
    log('雷达里引了库内文献的：%d 篇；新标成「库里有」的：%d 篇' % (n, m))
    return n


def fill_abstracts(max_calls=400, log=None, batch=50):
    """给雷达里没摘要的补摘要（OpenAlex，按 DOI 批量）。

    Crossref 的摘要看出版社脸色（Elsevier 一律没有、ACS 老文章 15%、Springer 56%）；OpenAlex 对
    Wiley/ACS/Nature 覆盖 95%+，Elsevier 也没有。每次最多 `max_calls` 批（一批 50 篇）：
    OpenAlex 按量计费，filter 查询 $0.10/千次，没 key 每天 $0.10 额度 —— 400 批 = $0.04，天天跑也在额度内。
    补过但对面也没有的记进 seen（`no_abstract`），不再重复问。返回 (补上几篇, 问了几篇)。
    """
    log = log or _log.info
    seen = load_seen()
    asked = set(seen.get('no_abstract') or [])
    con = store.connect()
    try:
        # Elsevier 两边都没有，不浪费额度
        rows = con.execute("""SELECT doi FROM works WHERE length(coalesce(abstract,''))<200
                              AND publisher NOT LIKE 'Elsevier%' ORDER BY published DESC""").fetchall()
        todo = [d for (d,) in rows if d not in asked][:max_calls * batch]
        if not todo:
            return 0, 0
        filled = 0
        for i in range(0, len(todo), batch):
            chunk = todo[i:i + batch]
            try:
                got = openalex.works_by_dois(chunk, allow_partial=True)
            except Exception as e:
                log('  OpenAlex 补摘要中断：%s' % str(e)[:80])
                break
            have = {}
            for w in got.values():
                d = (w.get('doi') or '').lower().replace('https://doi.org/', '')
                ab = openalex.restore_abstract(w.get('abstract_inverted_index'), limit=0)
                if d and ab:
                    have[d] = ab[:3000]
            con.executemany('UPDATE works SET abstract=? WHERE doi=?', [(a, d) for d, a in have.items()])
            con.commit()
            filled += len(have)
            asked.update(d for d in chunk if d not in have)
            heartbeat.progress('journalwatch-abstracts')
        seen['no_abstract'] = sorted(asked)
        save_seen(seen)
    finally:
        con.close()
    log('补摘要：问了 %d 篇，补上 %d 篇' % (len(todo), filled))
    return filled, len(todo)


MAX_ATTEMPTS = 4      # 刚登记的全文往往过几天才挂出来：取不到隔天再试，最多试四天


def enqueue_passing(items):
    """过线的进「待取」队列（seen['queue']: doi → {tier, lib_cites, title, attempts}）。已在证据库的不进。返回新入队几篇。"""
    seen = load_seen()
    q = seen.setdefault('queue', {})
    n = 0
    for w in items:
        d = catalog.norm_doi(w.get('doi'))
        if not d or not w.get('passes') or w.get('in_library') or d in q or d in (seen.get('harvested') or {}):
            continue
        q[d] = {'tier': w.get('tier'), 'lib_cites': w.get('lib_cites', 0), 'title': (w.get('title') or '')[:120],
                'venue': w.get('venue', ''), 'attempts': 0}
        n += 1
    save_seen(seen)
    return n


def next_to_harvest(limit=5):
    """队列里最该取的几篇：引库内越多越先，同分 A 先于 B 先于 C。返回 [(doi, info)]。"""
    q = load_seen().get('queue') or {}
    rows = [(d, i) for d, i in q.items() if i.get('attempts', 0) < MAX_ATTEMPTS]
    rows.sort(key=lambda x: (-x[1].get('lib_cites', 0), x[1].get('tier') or 'C'))
    return rows[:limit]


def mark_harvest(doi, ok, note=''):
    """取件结果回写：成了 → 出队进 harvested；没成 → attempts+1（到上限就留在队里不再试）。"""
    seen = load_seen()
    q = seen.setdefault('queue', {})
    d = catalog.norm_doi(doi)
    info = q.get(d) or {}
    if ok:
        q.pop(d, None)
        seen.setdefault('harvested', {})[d] = dict(info, when=_dt.date.today().isoformat())
    else:
        info['attempts'] = info.get('attempts', 0) + 1
        info['note'] = note[:80]
        q[d] = info
    save_seen(seen)
