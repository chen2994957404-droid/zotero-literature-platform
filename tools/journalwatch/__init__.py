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

from shared.adapters import crossref
from shared.kernel import catalog, heartbeat, paths
from shared.kernel.log import get_logger
from tools.journalwatch import store

_log = get_logger('journalwatch')

# 种子清单：ISSN 全部 2026-09-15 在 Crossref `/journals` 端点查证过（不是凭记忆写的）。
# 用户改 `journal_watch.json` 就行，这里只在文件不存在时用一次。
DEFAULT_JOURNALS = [
    {'name': 'Nature', 'issn': '0028-0836'},
    {'name': 'Science', 'issn': '0036-8075'},
    {'name': 'Nature Materials', 'issn': '1476-1122'},
    {'name': 'Nature Chemistry', 'issn': '1755-4330'},
    {'name': 'Nature Communications', 'issn': '2041-1723'},
    {'name': 'Science Advances', 'issn': '2375-2548'},
    {'name': 'Matter', 'issn': '2590-2385'},
    {'name': 'Chem', 'issn': '2451-9294'},
    {'name': 'Journal of the American Chemical Society', 'issn': '0002-7863'},
    {'name': 'Angewandte Chemie International Edition', 'issn': '1433-7851'},
    {'name': 'Advanced Materials', 'issn': '0935-9648'},
    {'name': 'Advanced Functional Materials', 'issn': '1616-301X'},
    {'name': 'Advanced Science', 'issn': '2198-3844'},
    {'name': 'Small', 'issn': '1613-6810'},
    {'name': 'Macromolecules', 'issn': '0024-9297'},
    {'name': 'ACS Macro Letters', 'issn': '2161-1653'},
    {'name': 'Chemistry of Materials', 'issn': '0897-4756'},
    {'name': 'ACS Nano', 'issn': '1936-0851'},
    {'name': 'Nano Letters', 'issn': '1530-6984'},
    {'name': 'ACS Central Science', 'issn': '2374-7943'},
    {'name': 'ACS Applied Materials & Interfaces', 'issn': '1944-8244'},
    {'name': 'Polymer Chemistry', 'issn': '1759-9954'},
    {'name': 'Materials Horizons', 'issn': '2051-6347'},
    {'name': 'Journal of Materials Chemistry A', 'issn': '2050-7488'},
    {'name': 'Chemical Society Reviews', 'issn': '0306-0012'},
    {'name': 'Progress in Polymer Science', 'issn': '0079-6700'},
    {'name': 'Chemical Engineering Journal', 'issn': '1385-8947'},
    {'name': 'Nature Reviews Materials', 'issn': '2058-8437'},
]

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
    return [j for j in d.get('journals', []) if j.get('issn') and not j.get('off')]


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
