# -*- coding: utf-8 -*-
"""wechat_import · 公众号推送 → Zotero 条目 + 一份现成的正文精读

**解决的真实问题**（用户 2026-09-06 定）：我们自己的正文精读，本来就是照着
「高分子学人」的推送学的 —— 那份是人写的，质量更高。既然取 PDF 的通道已经打通，
就该反过来用：**推送本身当正文精读**，我们只补它没有的东西（SI）。

所以一篇推送进来会变成四样东西：

    1. Zotero 里一个条目（按 Crossref 元数据建）—— 只有元数据，很轻
    2. `data/raw/<KEY>/main.pdf` · `si.pdf|docx` —— 正文与补充材料的**本地正本**
    3. `data/curated/<KEY>/summary.html` —— 推送正文，图内嵌，样式与我们的精读一致
    4. 状态库里一条 `main_summary` 完成记录，producer=`wechat`

**附件默认不传 Zotero**（用户 2026-09-06 定）：Zotero 官方存储免费只有 300 MB，
单个附件还有体积上限（实测 4.1 MB 过、5.1 MB 就 413）。建库本来就不需要 Zotero ——
先把文献落到本地，需要哪篇再 `upload_attachments(key)` 传上去。
卡在配额上的应该只是「传」，不该是「取」和「读」。

第 3 条是关键：有了它，`tools.deepread.run()` 会**跳过正文精读**（省钱、也不覆盖
人写的那份），只去做 SI，然后把 SI 合并进来 —— 「全文精读 = 公众号正文 + 我们的 SI」
就这么成立，不用改 deepread 一行代码。

**为什么住在 host/**：它要串起 `getpdf`（建条目、取 PDF）与 `deepread`
（状态标签、合并），跨工具的编排上浮到 host（硬规则 2）。

对外接口：
    parse_md(path)                  → 一篇 md → article（不联网、不写盘）
    list_dir(dir)                   → 目录里的 md，按推送日期从新到旧
    build_local(key, article)       → 落地 summary.html + meta.json + 状态记录
    import_one(path, ...)           → 一篇走完：建条目 → 取原件到本地 → 装精读
    import_many(paths, ...)         → 一批（单篇失败不拖累整批）
    upload_attachments(key)         → 把本地原件与精读传进 Zotero（按需，另一步）

**图为什么内嵌成 base64**：跟 `deepread` 的产物保持同一形状 —— 一个 HTML 文件
自带全部图，扔进 Zotero 附件就能看，也不怕微信图床哪天失效。
"""
import base64
import io
import json
import os
import shutil
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


JPEG_QUALITY = 82
# Zotero 会拒收太大的附件（实测 413）。综述那种 30 张图的推文，
# 按默认质量压完仍有 4 MB —— 超过这条线就降质量重来一次。
MAX_HTML_BYTES = 2_400_000
FALLBACK_QUALITY = 55


def parse_md(path):
    """一篇公众号 md → article dict。不联网、不写盘，纯读文件。"""
    text = io.open(path, encoding='utf-8', errors='replace').read()
    a = wechat_seed.parse_article(text)
    a['file'] = os.path.basename(path)
    return a


def list_dir(directory):
    """一个下载目录 → md 路径列表，**按推送日期从新到旧**。

    不能按文件名排 —— 下载工具的文件名是「期刊名+中文标题」，**不带日期**
    （wechat_seed 的第 2 号坑）。所以日期只能从正文里读。
    """
    seeds = wechat_seed.scan(directory)
    seeds.sort(key=lambda s: s['pubdate'] or '', reverse=True)
    return [os.path.join(directory, s['file']) for s in seeds]


def render_html(article, images, quality=JPEG_QUALITY):
    """article + 已下好的图 → 一份自带全部图的 HTML（图压成 JPEG 内嵌）。

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
            data, ctype = shrink(*images[b['url']], quality=quality)
            out.append('<img src="data:%s;base64,%s">'
                       % (ctype, base64.b64encode(data).decode()))
    return ('<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">'
            '<title>文献精读（公众号）</title><style>%s</style></head><body>%s'
            '</body></html>' % (CSS, '\n'.join(out)))


def _esc(s):
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def fetch_images(article, log=log.info):
    """把一篇里的图都下下来（**原样，不压**）→ {url: (bytes, ctype)}。

    压缩留到渲染那一步做 —— 一篇太大要降质量重来时，得从原图重压，
    对着压过一遍的图再压一遍只会越压越糊。
    """
    got = {}
    urls = [b['url'] for b in article.get('blocks', []) if b['kind'] == 'img']
    for i, u in enumerate(urls, 1):
        try:
            got[u] = wechat_seed.fetch_image(u)
        except Exception as e:
            log('  [跳过第%d张图] %s' % (i, e))
    return got


def shrink(data, ctype, quality=JPEG_QUALITY):
    """一张图 → 体积小得多的 JPEG（尺寸不变，只换编码）。压不动就还用原图。

    **为什么必须压**：推文的配图是 1080 宽的 PNG，一篇十几张就是好几 MB，
    内嵌成 base64 还要再涨三分之一。实测（2026-09-06）Zotero 传 4.1 MB 的
    附件能过、5.1 MB 就 413 —— 不压的话十几张图的那些篇根本传不上去。

    实测压缩比：2.12 MB → 0.56 MB，尺寸一个像素没动，只是 PNG → JPEG q82。
    """
    try:
        import fitz
        pix = fitz.Pixmap(data)
        if pix.colorspace is None or pix.n > 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)     # CMYK / 灰度等 → RGB
        if pix.alpha:
            pix = fitz.Pixmap(pix, 0)              # JPEG 不能带透明通道
        out = pix.tobytes('jpeg', jpg_quality=quality)
    except Exception:
        return data, ctype
    return (out, 'image/jpeg') if len(out) < len(data) else (data, ctype)


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
    if len(html) > MAX_HTML_BYTES and images:
        # 图特别多的（综述能有 30 张）按默认质量压完还是太大，Zotero 会拒收。
        # 从**原图**降质量重压一次，不是对着压过的再压。
        smaller = render_html(article, images, quality=FALLBACK_QUALITY)
        log('  [太大了] %d KB → %d KB（图片质量从 %d 降到 %d）'
            % (len(html) // 1024, len(smaller) // 1024,
               JPEG_QUALITY, FALLBACK_QUALITY))
        html = smaller
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
               upload=False, force=False, log=print):
    """一篇 md → Zotero 条目 + 本地原件 + 正文精读。**会写 Zotero**（建条目、打标签）。

    返回 dict(file, doi, key, action, summary, pdf, si, note)。`action` 沿用
    getpdf 的说法（created / exists / skipped / failed），好跟那条线对得上。

    `upload` 三档：`False`（默认，一个附件都不传）· `'summary'`（只传精读，
    它小、而且是你天天要看的）· `'all'`（连正文 PDF 与 SI 一起传，很占配额）。

    **库里已经有的条目不动它的合集** —— 用户的 178 个合集是按来源（大学→导师）
    分的，把已收藏的文献又塞进「LLM导入」会打乱他自己的心智模型。
    只有我们新建的条目才归到 `LLM导入/<用途>` 下。

    `with_si` 不传时**跟着 `with_pdf` 走**：这条线的整个意义就是「全文精读 =
    公众号的正文 + 我们做的 SI」，取了正文却不取 SI，那一半永远补不上。
    """
    from tools import getpdf
    from tools.deepread import tags as dr_tags

    out = {'file': os.path.basename(md_path), 'doi': '', 'key': '',
           'action': 'failed', 'summary': '', 'pdf': '', 'si': '', 'note': ''}
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

    # ① 先拿到 key。条目只有元数据，很轻 —— 贵的是附件，那是第 ③ 步的事。
    idx = getpdf.doi_index()
    key = idx.get(doi.strip().lower())
    if key:
        out['action'] = 'exists'
        log('  [已在库里] %s' % key)
    else:
        r = getpdf.stash(doi, None, purpose=purpose, index=idx, force=force)
        if not r['ok']:
            out['note'] = r['note']
            log('  [建条目失败] %s' % r['note'])
            return out
        key, out['action'] = r['item'], r['action']
        log('  [%s] %s' % (r['action'], key))
    out['key'] = key

    # ② 原件落到**本地正本**（raw/<key>/），Zotero 传不传是另一回事
    if with_pdf:
        out['pdf'] = _ensure_pdf(key, doi, log) or ''
        if out['pdf'] and with_si:
            out['si'] = _ensure_si(key, doi, log) or ''
    built = build_local(key, article, force=force, log=log)
    out['summary'] = built['path']

    # ③ 传 Zotero —— **默认不传**（用户 2026-09-06 定：先下到本地，需要的再传）
    if upload:
        upload_attachments(key, pdf=(upload == 'all'), si=(upload == 'all'), log=log)
    _try(lambda: dr_tags.set_state_tag(key, dr_tags.TAG_MAIN_WX, log=log),
         '打标签', log)
    return out


def _ensure_pdf(key, doi, log=print):
    """正文 PDF 的本地正本，没有就去取 → 路径或 ''。

    幂等判据是**本地正本在不在**，不是临时下载区里有没有 —— 取回来就搬走，
    临时区随时可清空。
    """
    from tools import getpdf
    from shared.adapters import zotero_client as Z
    dst = paths.local_pdf(key)
    if os.path.exists(dst) and os.path.getsize(dst) > 1024:
        log('  [正文PDF] 本地已有 %d MB' % (os.path.getsize(dst) // 1048576))
        return dst
    # Zotero 里已经有这篇的 PDF（用户自己存的、或早先传上去的）就拷过来。
    # **再去敲一次出版商是白敲** —— 封的是整个机构的 IP，代价全校担。
    had = _try(lambda: Z.find_pdf(key), '问 Zotero 有没有 PDF', log)
    if had and os.path.exists(had):
        paths.paper_raw_dir(key, create=True)
        shutil.copy2(had, dst)
        log('  [正文PDF] Zotero 里已有，拷进本地库')
        return dst
    # 取件是**最容易出岔子**的一步（浏览器会跳转、出版商会变卦），但它岔了
    # 不该连累后面 —— 推文精读本来就不需要 PDF。实测撞到过
    # `Page.evaluate: Execution context was destroyed`（2026-09-06）。
    got = _try(lambda: getpdf.fetch_one(doi), '取正文PDF', log) or {}
    if not (got.get('ok') and got.get('path')):
        log('  [没取到正文PDF] %s —— 精读照做，PDF 以后再补' % got.get('reason', ''))
        return ''
    paths.paper_raw_dir(key, create=True)
    shutil.move(got['path'], dst)
    log('  [正文PDF] %.1f MB → 本地库' % (os.path.getsize(dst) / 1048576))
    return dst


def _ensure_si(key, doi, log=print):
    """SI 原件的本地正本，没有就去取 → 路径或 ''。扩展名跟着来源走。"""
    from tools import getpdf
    have = paths.find_local_si(key)
    if have:
        log('  [SI] 本地已有')
        return have
    si = _try(lambda: getpdf.fetch_si_one(doi), '取SI', log) or {}
    if not (si.get('ok') and si.get('path')):
        log('  [SI] 没取到（%s）—— 正文照走' % si.get('reason', ''))
        return ''
    ext = os.path.splitext(si['path'])[1] or '.pdf'
    dst = paths.local_si(key, ext)
    paths.paper_raw_dir(key, create=True)
    shutil.move(si['path'], dst)
    log('  [SI] %d KB → 本地库' % (os.path.getsize(dst) // 1024))
    return dst


def upload_attachments(key, pdf=True, si=True, summary=True, log=print):
    """把这篇的本地原件与精读传进 Zotero。**每一份各自失败，互不牵连。**

    三样可以分开传，因为它们的性质不一样：**精读是人天天看的，而且小**
    （0.5~4 MB）；正文 PDF 与 SI 是给解析器吃的，动辄几十 MB
    （实测撞到过 34.9 MB 的综述）。所以默认的用法是「精读传上去、原件留本地」。

    这是「先下到本地，需要的再传」里的**传**那一半。为什么要分开：
    Zotero 官方存储免费只有 300 MB，而一篇正文 PDF 就 1～10 MB；
    附件还有单个体积上限（实测 4.1 MB 过、5.1 MB 就 413）。
    卡在这些限制上的应该只是「传」，不该是「取」和「读」。
    """
    from tools import getpdf
    from tools.deepread import batch as dr_batch

    pdf_path, si_path = paths.local_pdf(key), paths.find_local_si(key)
    if pdf and os.path.exists(pdf_path):
        r = _try(lambda: getpdf.attach_pdf(key, pdf_path), '传正文PDF', log)
        if r:
            log('  [正文PDF] %s' % ('传上去了' if r[0] else r[1]))
    if si and si_path:
        r = _try(lambda: getpdf.attach_si(key, si_path), '传SI', log)
        if r:
            log('  [SI] %s' % ('传上去了' if r[0] else r[1]))
    if summary:
        _try(lambda: dr_batch.upload_one(key, log=log), '传精读', log)


def _try(fn, what, log):
    """跑一步，出岔子只记一行、返回 None。

    这条线由五六个独立的小步骤串成（取正文、取SI、建条目、挂附件、打标签），
    照 `deepread` 的老规矩：**单步失败不拖累别的步骤**。
    早先没这么写，结果一份 23 MB 的 SI 传不上去，连带那篇的精读也没装上。
    """
    try:
        return fn()
    except Exception as e:
        log('  [%s失败] %s' % (what, str(e)[:120]))
        return None


def import_many(paths_, purpose='建库', with_pdf=False, upload=False,
                force=False, log=print):
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
                                  upload=upload, force=force, log=log))
        except Exception as e:
            log('  [失败] %s' % e)
            out.append({'file': os.path.basename(p), 'doi': '', 'key': '',
                        'action': 'failed', 'summary': '', 'pdf': '', 'si': '',
                        'note': str(e)[:200]})
    return out
