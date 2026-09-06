# -*- coding: utf-8 -*-
"""wechat_import · 公众号推送 → Zotero 条目 + 一份现成的正文精读

**解决的真实问题**（用户 2026-09-06 定）：我们自己的正文精读，本来就是照着
「高分子学人」的推送学的 —— 那份是人写的，质量更高。既然取 PDF 的通道已经打通，
就该反过来用：**推送本身当正文精读**，我们只补它没有的东西（SI）。

所以一篇推送进来会变成三样东西：

    1. Zotero 里一个条目（按 Crossref 元数据建，可选连正文 PDF 一起挂）
    2. `data/curated/<KEY>/summary.html` —— 推送正文，图内嵌，样式与我们的精读一致
    3. 状态库里一条 `main_summary` 完成记录，producer=`wechat`

第 3 条是关键：有了它，`tools.deepread.run()` 会**跳过正文精读**（省钱、也不覆盖
人写的那份），只去做 SI，然后把 SI 合并进来 —— 「全文精读 = 公众号正文 + 我们的 SI」
就这么成立，不用改 deepread 一行代码。

**为什么住在 host/**：它要串起 `getpdf`（建条目、取 PDF）与 `deepread`
（状态标签、合并），跨工具的编排上浮到 host（硬规则 2）。

对外接口：
    parse_md(path)                  → 一篇 md → article（不联网、不写盘）
    build_local(key, article)       → 落地 summary.html + meta.json + 状态记录
    import_one(path, ...)           → 全套（**会写 Zotero**，要 role 守卫）

**图为什么内嵌成 base64**：跟 `deepread` 的产物保持同一形状 —— 一个 HTML 文件
自带全部图，扔进 Zotero 附件就能看，也不怕微信图床哪天失效。
"""
import base64
import io
import json
import os
import time

from shared.adapters import wechat_seed
from shared.kernel import jobs, paths
from shared.kernel.log import get_logger

log = get_logger('wechat_import')

PRODUCER = 'wechat'
# 这份正文不是我们的提示词产的，我们的提示词升到几版都跟它无关 ——
# 记一个高得够不着的版本号，让 `jobs.stale('main_summary', ...)` 永远不会
# 把这些篇算进「该重跑」。用户定的：这些文献后续不再做正文精读。
PROMPT_VER = 999

CSS = ('body{max-width:820px;margin:0 auto;padding:24px;font-family:-apple-system,'
       '"Microsoft YaHei",sans-serif;line-height:1.85;color:#222;background:#fafafa}'
       'p{margin:12px 0;text-align:justify}img{max-width:100%;display:block;'
       'margin:18px auto;border:1px solid #eee;border-radius:6px;'
       'box-shadow:0 2px 8px rgba(0,0,0,.06)}'
       'h1{font-size:21px;line-height:1.5;color:#1a1a1a;margin:0 0 6px}'
       '.src{color:#888;font-size:13px;margin:0 0 24px;padding-bottom:14px;'
       'border-bottom:1px solid #e5e5e5}.src a{color:#5a6ec0}')


def parse_md(path):
    """一篇公众号 md → article dict。不联网、不写盘，纯读文件。"""
    text = io.open(path, encoding='utf-8', errors='replace').read()
    a = wechat_seed.parse_article(text)
    a['file'] = os.path.basename(path)
    return a


def render_html(article, images):
    """article + 已下好的图 → 一份自带全部图的 HTML。纯字符串处理。

    `images` 是 {url: (bytes, content_type)}；**取不到的图直接略过**
    （宁可少一张图，也不要在 Zotero 里留一个红叉）。
    """
    out = ['<h1>%s</h1>' % _esc(article.get('title', ''))]
    src = '来源：公众号「高分子学人」'
    if article.get('pubdate'):
        src += ' · %s' % article['pubdate']
    if article.get('doi'):
        src += ' · <a href="https://doi.org/%s">%s</a>' % (
            article['doi'], _esc(article['doi']))
    out.append('<p class="src">%s</p>' % src)
    for b in article.get('blocks', []):
        if b['kind'] == 'p':
            out.append('<p>%s</p>' % _esc(b['text']))
        elif b['url'] in images:
            data, ctype = images[b['url']]
            out.append('<img src="data:%s;base64,%s">'
                       % (ctype, base64.b64encode(data).decode()))
    return ('<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">'
            '<title>文献精读（公众号）</title><style>%s</style></head><body>%s'
            '</body></html>' % (CSS, '\n'.join(out)))


def _esc(s):
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def fetch_images(article, log=log.info):
    """把一篇里的图都下下来 → {url: (bytes, ctype)}。单张失败只跳过它。"""
    got = {}
    urls = [b['url'] for b in article.get('blocks', []) if b['kind'] == 'img']
    for i, u in enumerate(urls, 1):
        try:
            got[u] = wechat_seed.fetch_image(u)
        except Exception as e:
            log('  [跳过第%d张图] %s' % (i, e))
    return got


def build_local(key, article, images=None, force=False, log=print):
    """落地：summary.html + meta.json + 状态记录。**不碰 Zotero。**

    幂等：已经有 summary.html 且状态库说做过，就不重做（force 可强制）。
    返回 dict(key, path, bytes, images, skipped)。
    """
    key = paths.check_key(key)
    out = paths.summary(key)
    if not force and jobs.is_done(key, 'main_summary', require='summary'):
        log('  [跳过] 已有正文精读')
        return {'key': key, 'path': out, 'bytes': os.path.getsize(out),
                'images': 0, 'skipped': True}
    if images is None:
        images = fetch_images(article, log=log)
    html = render_html(article, images)
    paths.paper_dir(key, create=True)
    with jobs.track(key, 'main_summary', producer=PRODUCER,
                    prompt_ver=PROMPT_VER, model=PRODUCER):
        io.open(out, 'w', encoding='utf-8').write(html)
    _write_meta(key, article)
    log('  [正文精读] %s %d KB，图 %d 张（人写的，没花钱）'
        % (os.path.basename(out), round(len(html) / 1024), len(images)))
    return {'key': key, 'path': out, 'bytes': len(html),
            'images': len(images), 'skipped': False}


def _write_meta(key, article):
    """meta.json —— 问答与向量化靠它知道这篇是什么。`source` 标明是谁写的。"""
    try:
        meta = {'key': key, 'title': article.get('title', ''),
                'DOI': article.get('doi', ''), 'date': article.get('pubdate', ''),
                'model': PRODUCER, 'source': '公众号/高分子学人',
                'wechat_file': article.get('file', ''),
                'time': time.strftime('%Y-%m-%d %H:%M')}
        old = {}
        if os.path.exists(paths.meta(key)):
            try:
                old = json.load(io.open(paths.meta(key), encoding='utf-8'))
            except Exception:
                old = {}
        for k, v in list(meta.items()):
            if not v and old.get(k):
                meta[k] = old[k]
        json.dump(meta, io.open(paths.meta(key), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
    except Exception as e:
        log.warning('meta.json 没写成: %s', e)


# ── 写 Zotero 的那一段（调用方必须先过 role 守卫）────────────────────
def import_one(md_path, purpose='建库', with_pdf=False, with_si=None,
               force=False, log=print):
    """一篇 md → Zotero 条目 + 正文精读附件 + 状态标签。**会写 Zotero。**

    返回 dict(file, doi, key, action, summary, note)。`action` 沿用 getpdf 的说法
    （created / exists / skipped / failed），好跟那条线对得上。

    **库里已经有的条目不动它的合集** —— 用户的 178 个合集是按来源（大学→导师）
    分的，把已收藏的文献又塞进「LLM导入」会打乱他自己的心智模型。
    只有我们新建的条目才归到 `LLM导入/<用途>` 下。

    `with_si` 不传时**跟着 `with_pdf` 走**：这条线的整个意义就是「全文精读 =
    公众号的正文 + 我们做的 SI」，取了正文却不取 SI，那一半永远补不上。
    """
    from tools import getpdf
    from tools.deepread import batch as dr_batch, tags as dr_tags

    out = {'file': os.path.basename(md_path), 'doi': '', 'key': '',
           'action': 'failed', 'summary': '', 'note': ''}
    article = parse_md(md_path)
    doi = article.get('doi')
    out['doi'] = doi
    if not doi:
        out['action'] = 'skipped'
        out['note'] = '这篇推送里没有 DOI（多半不是论文推送）'
        log('  [跳过] %s' % out['note'])
        return out

    if with_si is None:
        with_si = with_pdf
    idx = getpdf.doi_index()
    key = idx.get(doi.strip().lower())
    pdf_path, si_path = None, None
    if with_pdf and not key:
        got = getpdf.fetch_one(doi)
        pdf_path = got.get('path') if got.get('ok') else None
        if not pdf_path:
            log('  [没取到正文PDF] %s —— 条目照建，PDF 以后再补'
                % got.get('reason', ''))
        elif with_si:
            si = getpdf.fetch_si_one(doi)
            si_path = si.get('path') if si.get('ok') else None
            log('  [SI] %s' % ('%d KB' % (si['bytes'] // 1024) if si_path
                               else '没取到（%s）—— 正文照走' % si.get('reason', '')))
    if key:
        out['action'] = 'exists'
        log('  [已在库里] %s' % key)
    else:
        r = getpdf.stash(doi, pdf_path, purpose=purpose, index=idx, force=force)
        if not r['ok']:
            out['note'] = r['note']
            log('  [建条目失败] %s' % r['note'])
            return out
        key, out['action'] = r['item'], r['action']
        log('  [%s] %s %s' % (r['action'], key, r['note']))

    out['key'] = key
    if si_path:
        done, why = getpdf.attach_si(key, si_path)
        log('  [SI 附件] %s' % ('挂上了' if done else why))
    built = build_local(key, article, force=force, log=log)
    out['summary'] = built['path']
    dr_batch.upload_one(key, force=force, log=log)
    dr_tags.set_state_tag(key, dr_tags.TAG_MAIN_WX, log=log)
    return out


def import_many(paths_, purpose='建库', with_pdf=False, force=False, log=print):
    """一批 md。**单篇失败不拖累整批**，最后返回每篇的结果列表。

    取正文 PDF 时每篇之间**照 `getpdf.GAP` 等一会儿**：出版商封的是整个机构的
    IP，代价全校担。这条线一次只导几篇，慢一点无所谓。
    """
    import time

    from tools import getpdf

    out = []
    for i, p in enumerate(paths_, 1):
        log('[%d/%d] %s' % (i, len(paths_), os.path.basename(p)))
        if with_pdf and i > 1:
            time.sleep(getpdf.GAP)
        try:
            out.append(import_one(p, purpose=purpose, with_pdf=with_pdf,
                                  force=force, log=log))
        except Exception as e:
            log('  [失败] %s' % e)
            out.append({'file': os.path.basename(p), 'doi': '', 'key': '',
                        'action': 'failed', 'summary': '', 'note': str(e)[:200]})
    return out
