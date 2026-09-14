# -*- coding: utf-8 -*-
"""精读金标集：把「人写的范文」和「英文原件」配成对（2026-09-14）。

**解决的真实问题**：精读模板一直是「照描述仿高分子学人」写的，好不好只能模型之间互比，
没有绝对参照（踩坑 #115）。而 B 机上存着 870 篇高分子学人推送，每篇文末有 DOI ——
DOI → 取正文进证据库 → 推文原文存成 `reference.md`，就有了几百对
「英文原文 ↔ 人写的中文精读」。这份东西三处都用得上：

    1. 评测：任何模板改动，自动比「离范文还差多远」，不用用户逐篇打分
    2. 本地模型能不能胜任：同一批文献换模型跑，用范文比分差
    3. 将来若微调：这就是训练对

**跟 `import_one` 的区别**：那条线把推文**当精读装上**（`summary.html`，之后不再跑正文精读）；
这条线把推文**当标尺存起来**（`reference.md`），**这些文献照样要跑我们自己的精读**，
否则没东西可比。所以这里绝不写 `summary.html`、不写 Zotero、不打标签。

对外接口：
    pair(md_path, allow_fetch, log)      → 一篇：落原件 + 存范文 + 记索引
    build(files, allow_fetch, log)       → 一批（单篇失败不拖累整批）
    load_index()                         → {id: 记录}
    render_reference(article)            → 推文 dict → reference.md 的文本（纯函数）
"""
import io
import json
import os
import time

from shared.kernel import catalog, paths
from shared.kernel.log import get_logger

log = get_logger('wechat_golden')

# 完整推送实测 4954–10970 字（2026-09-05 量的 10 篇）；残件 557–826 字。
# 卡在中间偏下：短于这个数的不是范文，是没展开就存了的残件，不配对。
MIN_REF_CHARS = 2500


def render_reference(article):
    """推文 dict → reference.md 文本。图只留链接不下载：标尺比的是文字。"""
    head = ['# ' + (article.get('title') or ''),
            '',
            '来源: 高分子学人 · %s · %s' % (article.get('pubdate') or '?',
                                        article.get('file') or ''),
            'DOI: ' + (article.get('doi') or ''),
            '',
            '---',
            '']
    body = []
    for b in article.get('blocks') or []:
        if b.get('kind') == 'img':
            body.append('![](%s)' % b.get('url', ''))
        else:
            body.append(b.get('text', ''))
        body.append('')
    return '\n'.join(head + body).rstrip() + '\n'


def _chars(article):
    return sum(len(b.get('text', '')) for b in article.get('blocks') or []
               if b.get('kind') == 'p')


def load_index():
    p = paths.golden_index()
    if not os.path.exists(p):
        return {}
    try:
        return json.load(io.open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _save_index(idx):
    p = paths.golden_index()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    io.open(tmp, 'w', encoding='utf-8').write(json.dumps(idx, ensure_ascii=False, indent=1))
    os.replace(tmp, p)


def pair(md_path, allow_fetch=True, log=print):
    """一篇推文 → 配对记录 dict(file, doi, id, action, chars, pdf, si, note)。

    `action`：`paired` 这次配上了 / `exists` 早配过 / `skipped` 不配（没 DOI、残件）
    / `failed` 原件没拿到。原件走 `getpdf.land()`：证据库有就用、Zotero 有就拷、
    再没有才向出版商取（`allow_fetch=False` 时不取，「先看手上有多少能配」）。
    """
    from tools import getpdf
    from host.wechat_import import parse_md

    out = {'file': os.path.basename(md_path), 'doi': '', 'id': '', 'action': 'skipped',
           'chars': 0, 'pdf': False, 'si': False, 'note': ''}
    a = parse_md(md_path)
    out['doi'] = a.get('doi') or ''
    out['chars'] = _chars(a)
    if not out['doi']:
        out['note'] = '推送里没有 DOI（多半不是论文推送）'
        return out
    if out['chars'] < MIN_REF_CHARS:
        out['note'] = '只有 %d 字，是残件不是范文' % out['chars']
        return out

    r = getpdf.land(out['doi'], with_si=True, allow_fetch=allow_fetch)
    out['id'] = r.get('id') or ''
    out['pdf'], out['si'] = bool(r.get('pdf')), bool(r.get('si'))
    if not r.get('ok'):
        out['action'] = 'failed'
        out['note'] = r.get('note') or '正文没拿到'
        log('  [没原件] %s —— %s' % (out['doi'], out['note']))
        return out

    pid = out['id']
    ref = paths.reference(pid)
    fresh = not os.path.exists(ref)
    if fresh:
        os.makedirs(os.path.dirname(ref), exist_ok=True)
        io.open(ref, 'w', encoding='utf-8').write(render_reference(a))
    catalog.register(pid, reference='高分子学人', reference_file=out['file'])

    idx = load_index()
    idx[pid] = {'id': pid, 'doi': out['doi'], 'title': a.get('title') or '',
                'file': out['file'], 'pubdate': a.get('pubdate') or '',
                'chars': out['chars'],
                'imgs': sum(1 for b in a['blocks'] if b['kind'] == 'img'),
                'pdf': out['pdf'], 'si': out['si'],
                'paired_at': idx.get(pid, {}).get('paired_at') or time.strftime('%Y-%m-%d %H:%M')}
    _save_index(idx)
    out['action'] = 'paired' if fresh else 'exists'
    log('  [%s] %s ← %s（%d 字%s）' % (out['action'], pid, out['doi'], out['chars'],
                                        '' if out['si'] else '，无 SI'))
    return out


def build(files, allow_fetch=True, log=print):
    """一批推文配对。单篇出错记下来继续，最后返回全部记录。"""
    res = []
    for i, p in enumerate(files, 1):
        log('[%d/%d] %s' % (i, len(files), os.path.basename(p)[:50]))
        try:
            res.append(pair(p, allow_fetch=allow_fetch, log=log))
        except Exception as e:                       # 一篇炸了不该拖累整批
            log('  [出错] %s' % e)
            res.append({'file': os.path.basename(p), 'doi': '', 'id': '',
                        'action': 'failed', 'chars': 0, 'pdf': False, 'si': False,
                        'note': str(e)})
    return res


def rewrite_references(files, log=print):
    """只重写已配对文献的 reference.md（解析规则变了之后用），不取件、不动索引 → 重写篇数。

    2026-09-14 第一次用：段界规则修好之前，范文里「Question → 总之 → 通俗理解」被拼成一段。
    """
    from host.wechat_import import parse_md
    n = 0
    for p in files:
        a = parse_md(p)
        pid = catalog.find(a.get('doi') or '')
        if not pid or not os.path.exists(paths.reference(pid)):
            continue
        io.open(paths.reference(pid), 'w', encoding='utf-8').write(render_reference(a))
        n += 1
    log('重写了 %d 篇范文' % n)
    return n


def summarize(res):
    """给人看的一段汇总。"""
    n = lambda a: sum(1 for r in res if r['action'] == a)
    lines = ['金标配对：新配 %d，早配过 %d，原件没拿到 %d，不配 %d（共 %d）'
             % (n('paired'), n('exists'), n('failed'), n('skipped'), len(res)),
             '现在金标集共 %d 对（含 SI 的 %d）' % (
                 len(load_index()), sum(1 for v in load_index().values() if v.get('si')))]
    for r in res:
        if r['action'] in ('failed', 'skipped') and r['doi']:
            lines.append('  %s %s —— %s' % (r['action'], r['doi'], r['note']))
    return '\n'.join(lines)
