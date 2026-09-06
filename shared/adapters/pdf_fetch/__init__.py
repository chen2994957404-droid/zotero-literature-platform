# -*- coding: utf-8 -*-
"""pdf_fetch · 出版商全文基础件（公理：一个 DOI → 这篇文献的 PDF 字节）

**为什么有这块（2026-09-04 建）**：库里补文献时，元数据能从 crossref 拿，
正文 PDF 却一直得人工一篇篇点。付费文献拿不到的根因不是权限，是**运输方式** ——
2026-09-04 实测过两条路：

  - `requests` + 机构 cookie：**过不了出版商的反爬**（旧的 AutoPAPER-SCU 就栽在这，
    它 `papers/` 里四个 PDF 全是开放获取，一篇付费的都没下来过）
  - **驱动一个人已经在用的真实浏览器**：可以。人机验证是「进门验一次」不是「每篇验一次」，
    验过之后同一个浏览器里后续文章都顺

所以这块的形状是：**不自己发 HTTP，而是接管一个已经开着的浏览器**。
机构订阅靠出口 IP 生效，浏览器天然带着；反爬看的是真实浏览器指纹，也天然带着。
换句话说，**权限和反爬这两件最难的事，都不是这块要解决的** —— 它只负责导航和取字节。

对外接口：
  - is_available()          → playwright 装了没（没装时上层要给人话，不是 ImportError）
  - probe(cdp_url)          → 那个浏览器连不连得上 → dict
  - fetch(doi, ...)         → dict，见下面 REASONS
  - pdf_url_of(page)        → 当前页面上的 PDF 直链候选（供上层排查用）

`fetch` **不抛异常表示「这篇没拿到」** —— 拿不到是常态（没订阅、撞验证码、
页面改版），每一种的处置都不同，所以用 `reason` 区分，让调用方决定跳过还是停下。
真正的异常只留给「环境不对」（没装 playwright、浏览器连不上）。

⚠ 这块**不知道文件该存哪**，也不碰 Zotero —— 那些是 tools 层的事。

依赖：playwright（**延迟 import**：A 机不装也要能 import 本模块，
否则架构守卫、体检的导入检查、pytest 收集会一起挂）。
"""
import base64
import re

from shared.kernel import config, errors
from shared.kernel.log import get_logger

log = get_logger('pdf_fetch')

# 浏览器的调试口。**故意不用 Chromium 的惯例端口 9222** —— 运行端实测那个口
# 被一个普通 Chrome 进程占着（它的命令行里根本没有 --remote-debugging-port，
# 多半是某个扩展），对 /json/version 回 404。撞上它的后果很阴：
# 浏览器起得来、端口也「通」，只是永远连不上，看着像代码坏了。
# 需要时用户可在控制面板改 BROWSER_CDP_URL。
DEFAULT_CDP = 'http://127.0.0.1:9333'

# 单篇 PDF 的上限。base64 过 CDP 桥要膨胀 ~1/3，太大的（整期合订本）不该走这条路。
MAX_PDF_BYTES = 80 * 1024 * 1024

# 一篇最多试几个候选地址。**必须有上限** —— 候选会在过程中长出新的
# （阅读器页面里嵌的东西也算候选），没有上限就可能在一堆嵌套里绕下去，
# 而每绕一次都是一次真实的出版商请求。
MAX_TRIES = 8

# fetch 的 reason 取值 —— 每一种的处置都不同，别合并
REASONS = {
    'ok': '拿到了',
    'captcha': '撞上人机验证 —— 要人在那个浏览器里点一下，之后同一浏览器会顺畅一阵',
    'no_access': '页面在，但没有全文权限（这本刊学校没订，或者当前出口 IP 不是机构）',
    'no_pdf_link': '页面在、也像有权限，但找不到 PDF 直链（多半是这家出版商的页面改版了）',
    'not_pdf': '拿到了东西但不是 PDF（多半被挡回了登录页或验证页）',
    'too_big': '文件超过上限，没往回传',
    'navigate_failed': '页面根本打不开',
    'no_si': '这篇没挂补充材料，或者挂的全是视频之类（那种我们不要）',
}


class BrowserUnavailable(errors.ExternalServiceError):
    """连不上那个浏览器 —— 它没开，或者没带调试口启动。可重试。"""


class PlaywrightMissing(errors.ConfigError):
    """这台机器没装 playwright。装一次的事，不是运行期故障。"""


def cdp_url():
    """浏览器调试口地址。走 config，不写死（红线 #3）。"""
    return config.get_key('BROWSER_CDP_URL', default='') or DEFAULT_CDP


def is_available():
    """playwright 装了没。上层据此给人话，而不是让 ImportError 冒到用户脸上。"""
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def _sync_api():
    """延迟 import —— 见模块 docstring 里为什么不能在顶层 import。"""
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        raise PlaywrightMissing(
            '这台机器没装 playwright，取全文要用它驱动浏览器。'
            '装一次：pip install playwright')


def probe(url=None):
    """那个浏览器连不连得上 → dict(ok, cdp, pages, error)。

    单独一个 probe 是因为**「浏览器没开」和「这篇拿不到」要分开报** ——
    前者是人要去做一件事，后者是这篇跳过就好。
    """
    target = url or cdp_url()
    if not is_available():
        return {'ok': False, 'cdp': target, 'error': 'playwright 没装'}
    sync_playwright = _sync_api()
    pw = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(target)
        ctxs = browser.contexts
        pages = sum(len(c.pages) for c in ctxs)
        browser.close()
        return {'ok': True, 'cdp': target, 'pages': pages}
    except Exception as e:
        return {'ok': False, 'cdp': target, 'error': f'{type(e).__name__}: {e}'}
    finally:
        if pw is not None:
            try:
                pw.stop()
            except Exception:
                pass


# ── 页面上的判断 ────────────────────────────────────────────────────────────
# 这几段 JS 住在这里而不是上层：**它们描述的是「出版商网站长什么样」**，
# 页面改版就只改这一个文件。这正是 adapters 这一环存在的理由。

_JS_STATE = """() => {
  const t = document.body ? document.body.innerText : '';
  const has = s => t.indexOf(s) >= 0;
  const meta = document.querySelector('meta[name="citation_pdf_url"]');
  const sels = ['a.download-link', 'a[href*="/pdfft"]', 'a[data-test="pdf-link"]',
                'a[href*="/doi/pdf/"]', 'a[href*="/content/pdf/"]',
                'a[href*="articlepdf"]', 'a[href$=".pdf"]'];
  // 图片要滤掉：ScienceDirect 的 a.download-link 也用在「下载这张图」上，
  // 不滤的话第一个候选会是 gr1_lrg.jpg，白跑一趟还会因为跨域报错。
  const isImg = u => /\\.(jpg|jpeg|png|gif|svg|webp|tif)(\\?|#|$)/i.test(u);
  // **补充材料必须从正文候选里滤掉**，这是最阴的一种错：文件下来了、大小也正常，
  // 内容却是 SI 不是正文。2026-09-05 实测 Wiley 就这么中过一次。
  // 但滤掉不等于扔掉 —— 它们收进 si 那一列，取 SI 的时候正好用。
  // `article-supplement` 是 ACS 2026 换到 Silverchair 之后的新规则
  const isSupp = u => /downloadSupplement|suppl_file|[-_]sup[-_]|SuppMat|supplementary|mmc\\d|MOESM|article-supplement/i.test(u);
  const hits = [];
  const push = u => {
    if (u && !isImg(u) && !isSupp(u) && hits.indexOf(u) < 0) hits.push(u);
  };
  if (meta && meta.content) push(meta.content);
  for (const s of sels) {
    const a = document.querySelector(s);
    if (a && a.href) push(a.href);
  }

  // ── 补充材料：连同链接文字一起收，光看 URL 分不出「实验数据」还是「视频」──
  // 2026-09-06 实测：Wiley 那篇的正文 SI 和演示视频**编号都是 sup-0001**，
  // 靠编号排序根本分不开；Elsevier 是 mmc1.docx / mmc2.mp4 / mmc3.mp4。
  // 所以判据是**类型**，不是顺序。
  const si = [];
  const seen = new Set();
  for (const a of document.querySelectorAll('a[href]')) {
    if (!isSupp(a.href)) continue;
    if (seen.has(a.href)) continue;
    seen.add(a.href);
    si.push({url: a.href,
             text: (a.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 90)});
  }
  // ACS 不直接列文件，只给一个 /doi/suppl/<doi> 的入口，要再进一层
  let suppPage = '';
  for (const a of document.querySelectorAll('a[href*="/doi/suppl/"]')) {
    suppPage = a.href; break;
  }
  return {
    url: location.href,
    title: (document.querySelector('h1') || {}).innerText || document.title || '',
    captcha: has('Are you a robot') ||
             (has('Just a moment') && t.toLowerCase().indexOf('checking') >= 0),
    paywall: has('Get Access') || has('Purchase PDF') || has('Get rights and content')
             && !hits.length,
    candidates: hits,
    si: si,
    suppPage: suppPage,
  };
}"""

_JS_GRAB = """async (u) => {
  try {
    const r = await fetch(u, {credentials: 'include'});
    if (!r.ok) return {ok: false, status: r.status};
    const b = await r.blob();
    if (b.size > %d) return {ok: false, tooBig: b.size};
    const buf = await b.arrayBuffer();
    let s = ''; const bytes = new Uint8Array(buf);
    const CH = 0x8000;
    for (let i = 0; i < bytes.length; i += CH) {
      s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
    }
    return {ok: true, type: b.type, size: b.size, b64: btoa(s)};
  } catch (e) { return {ok: false, err: String(e)}; }
}""" % MAX_PDF_BYTES


_JS_GRAB_HERE = """async () => {
  try {
    const r = await fetch(location.href, {credentials: 'include'});
    if (!r.ok) return {ok: false, status: r.status};
    const b = await r.blob();
    if (b.size > %d) return {ok: false, tooBig: b.size};
    const buf = await b.arrayBuffer();
    let s = ''; const bytes = new Uint8Array(buf);
    const CH = 0x8000;
    for (let i = 0; i < bytes.length; i += CH) {
      s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
    }
    return {ok: true, type: b.type, size: b.size, b64: btoa(s)};
  } catch (e) { return {ok: false, err: String(e)}; }
}""" % MAX_PDF_BYTES


def pdf_url_of(page):
    """当前页面上的 PDF 直链候选（按可信度排序）。排查时单独用得上。"""
    return page.evaluate(_JS_STATE).get('candidates') or []


def _looks_like_pdf(head, mime):
    """PDF 的magic number 是 %PDF —— 比 MIME 可信，出版商常把类型写错。"""
    return head[:4] == b'%PDF' or 'pdf' in (mime or '')


# 阅读器页面里嵌着的东西 —— 很多出版商把真身藏在 iframe 里（Wiley 实测）
_JS_EMBEDS = """() => Array.from(
    document.querySelectorAll('iframe[src], embed[src], object[data]'))
  .map(e => e.src || e.data)
  .filter(u => u && !/^(about|blob|data):/.test(u))"""

# 明显不是正文的东西，进候选队列之前先滤掉
_JUNK_RE = re.compile(
    r'\.(jpg|jpeg|png|gif|svg|webp|tif)(\?|#|$)'
    r'|downloadSupplement|suppl_file|[-_]sup[-_]|SuppMat|supplementary'
    r'|teaser|/cookie|/consent|doubleclick|googletag', re.I)


def _worth_trying(url):
    """这个地址值不值得试。滤的是图片、补充材料、广告/同意书之类的杂物。"""
    return bool(url) and url.startswith('http') and not _JUNK_RE.search(url)


# ── 补充材料：挑出「实验那份」 ──────────────────────────────────────────
# 2026-09-06 实测三家出版商的真实 SI 清单：
#   Elsevier : mmc1.docx（12MB，要的）· mmc2.mp4 · mmc3.mp4
#   Wiley    : ...sup-0001-SuppMat.pdf（要的）· ...sup-0001-MovieS1.mp4
#   ACS      : 页面上只给一个 /doi/suppl/<doi> 入口，要再进一层
#
# 判据必须是**类型**，不是顺序：Wiley 那两个的编号**都是 sup-0001**，
# 按序号排根本分不开；而且它的 URL 是 `downloadSupplement?...` 看不出扩展名 ——
# **扩展名只出现在链接文字里**。所以判断要把 URL 和链接文字**合起来看**。

# ⚠ 结尾用 `(?![A-Za-z0-9])` 而不是 `$`：我们搜的是 **URL 和链接文字拼起来的一串**，
# 扩展名后面往往还跟着别的内容（`mmc1.docx Download: Download Word document`）。
# 用 `$` 的话只有正好在末尾才匹配得上 —— 这个错曾被「挑不出好的就退而求其次」
# 掩盖着，直到把「退而求其次」关掉才露出来（2026-09-06）。
SI_GOOD_RE = re.compile(r'\.(pdf|docx?|txt)(?![A-Za-z0-9])', re.I)
# ACS 2026 换到 Silverchair 之后的新规则：
#   /<刊代码>/article-supplement/<资源id>/<格式>/<文件名>/
#   例：/mamobx/article-supplement/5416232/docx/ma-2026-01758h_si_001/
# **格式写在路径里，文件名后面没有扩展名** —— 只看扩展名的判据认不出它。
SI_PATH_FMT_RE = re.compile(r'/article-supplement/\d+/(pdf|docx?|txt)/', re.I)
SI_BAD_RE = re.compile(
    r'\.(mp4|avi|mov|wmv|mkv|webm|mp3|wav|zip|rar|7z|tar|gz)(?![A-Za-z0-9])'
    r'|movie|video|animation', re.I)


def si_format(c):
    """这个 SI 候选是什么格式 → 'pdf' / 'docx' / 'txt'，判不出返回空串。

    两种写法都要认：
      - 扩展名在名字里（Elsevier `mmc1.docx`、Wiley 链接文字 `...SuppMat.pdf`）
      - **格式写在路径里**（ACS 新规则 `/article-supplement/5416232/docx/xxx_si_001/`，
        文件名后面根本没有扩展名）

    「判得出格式」正是「这是个文件而不是锚点」的判据 ——
    比「名字里有没有点号」可靠得多。
    """
    url, text = c.get('url', ''), c.get('text', '')
    m = SI_PATH_FMT_RE.search(url)
    if m:
        return m.group(1).lower()
    m = SI_GOOD_RE.search(url + ' ' + text)
    return m.group(1).lower() if m else ''


def pick_si(cands, loose=False):
    """一堆 SI 链接 → 最可能是「实验部分」的那一个（没有就返回 None）。

    `cands` 是 [{url, text}, ...]。返回同样的 dict。

    排序办法：先扔掉明显是视频/压缩包的，再优先扩展名像文档的，
    同档保持页面上的原顺序（第一个通常就是正文 SI）。
    **宁可少下一个也不要下错** —— 下错的代价是几十 MB 视频占掉 Zotero 配额，
    而且解析器拿它没办法。
    """
    good, rest = [], []
    for c in (cands or []):
        blob = (c.get('url', '') + ' ' + c.get('text', ''))
        if SI_BAD_RE.search(blob):
            continue                      # 视频、压缩包：直接不要
        (good if si_format(c) else rest).append(c)
    # 默认**只认像文档的**。放宽会把「跳到补充材料那一节」的锚点当成文件 ——
    # 2026-09-06 实测 ACS 就这样：`?goto=supporting-info` 也被收进了候选，
    # 取回来是 391 KB 的 HTML。锚点不是文件，宁可说「没有」也别下错。
    pool = good if good else (rest if loose else [])
    return pool[0] if pool else None


def _via_request(ctx, url):
    """用浏览器上下文自己的 request 去取 → 字节，或 None。

    它共享浏览器的 cookie，但**不受页面的同源策略限制** ——
    这正是跨域附件（Elsevier 的 SI 挂在 ars.els-cdn.com 上）唯一够得着的办法。

    ⚠ 对**正文**不管用：实测 ScienceDirect 的正文签名直链用它取是 403
    （少了真实浏览器的指纹）。所以它只当 SI 的第三招，不是万能钥匙。
    """
    try:
        r = ctx.request.get(url, timeout=120000)
        if not r.ok:
            return None
        body = r.body()
        ctype = (r.headers or {}).get('content-type', '')
        return _decode({'ok': True, 'type': ctype,
                        'b64': base64.b64encode(body).decode()}, 'si')
    except Exception:
        return None


def _si_name(pick):
    """给这份 SI 起个像样的文件名 —— 优先用出版商自己的名字。

    Wiley 的 URL 是 `downloadSupplement?...`，扩展名**只在链接文字里**
    （`adfm202009017-sup-0001-SuppMat.pdf`），所以两个地方都要看。
    起不出来就返回空串，让调用方自己定。
    """
    import os
    import urllib.parse
    for cand in (pick.get('text', ''), urllib.parse.unquote(pick.get('url', ''))):
        for tok in re.split(r'[\s/\?&=]+', cand):
            if SI_GOOD_RE.search(tok) and len(tok) > 4:
                return os.path.basename(tok)
    # ACS 新规则：名字和格式分在路径的两段里，拼起来
    m = SI_PATH_FMT_RE.search(pick.get('url', ''))
    if m:
        stem = [t for t in pick.get('url', '').rstrip('/').split('/') if t][-1]
        return f'{stem}.{m.group(1).lower()}'
    return ''


def _decode(got, want='pdf'):
    """浏览器那边取回来的东西 → 字节；不合格就返回 None。

    几趟取字节的收尾一模一样，抽出来，免得判断走散
    （走散的后果是「一趟严一趟松」，而松的那趟会赢）。

    `want='pdf'` 只认 PDF（正文必须是 PDF，后面要送去解析）。
    `want='si'` 放宽到 **PDF 或 Office 文档** —— 实测库里的 SI
    是 19 个 .pdf + 13 个 .docx，docx 占了四成，只认 PDF 等于扔掉四成。
    但**永远不认 HTML**：那多半是被挡回了登录页或验证页。
    """
    if not got or not got.get('ok') or not got.get('b64'):
        return None
    raw = base64.b64decode(got['b64'])
    if _looks_like_pdf(raw[:4], got.get('type')):
        return raw
    if want == 'si':
        mime = (got.get('type') or '').lower()
        if 'html' in mime or raw[:9].lower().startswith(b'<!doctype'):
            return None
        # .docx/.xlsx 都是 zip 包，魔数是 PK
        if raw[:4] == b'PK' or 'officedocument' in mime or 'msword' in mime:
            return raw
    return None


def fetch(doi, url=None, timeout=90, settle=6, kind='fulltext'):
    """一个 DOI → dict(ok, reason, pdf, landing, title, pdf_url, filename)。

    `kind='fulltext'` 取正文；`kind='si'` 取补充材料里**实验那份**
    （挑法见 `pick_si`：按类型不按顺序，视频一律不要）。

    `settle` 是落地后多等几秒：出版商页面普遍是前端渲染，
    `domcontentloaded` 时链接还没长出来。宁可多等，重试更贵。
    """
    sync_playwright = _sync_api()
    out = {'ok': False, 'reason': 'navigate_failed', 'doi': doi,
           'pdf': b'', 'landing': '', 'title': '', 'pdf_url': '', 'filename': ''}
    pw = None
    try:
        pw = sync_playwright().start()
        try:
            browser = pw.chromium.connect_over_cdp(url or cdp_url())
        except Exception as e:
            raise BrowserUnavailable(
                f'连不上浏览器（{url or cdp_url()}）：{e}。'
                '它需要带着调试口启动，而且里面有人过过一次人机验证 —— '
                '订阅权限和已经通过的人机验证都在它身上。')
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        try:
            page.goto(f'https://doi.org/{doi}',
                      wait_until='domcontentloaded', timeout=timeout * 1000)
            page.wait_for_timeout(settle * 1000)

            st = page.evaluate(_JS_STATE)
            out['landing'] = st.get('url', '')
            out['title'] = (st.get('title') or '').strip()

            if st.get('captcha'):
                out['reason'] = 'captcha'
                return out
            if kind == 'si':
                # ⚠ **先滚一遍页面**：ACS 的 SI 链接是懒加载的，不滚到底
                # 根本不出现在 DOM 里。2026-09-06 头一回就栽在这 ——
                # 在 127 万字符的源码里搜了半天，得出「ACS 取不到」的结论，
                # 而真相只是那一段还没渲染出来。
                # **说「页面上没有」之前，先确认「页面已经长全了」。**
                for _ in range(6):
                    page.evaluate('() => window.scrollBy(0, '
                                  'document.body.scrollHeight / 5)')
                    page.wait_for_timeout(1000)
                page.wait_for_timeout(2000)
                st = page.evaluate(_JS_STATE)
                pick = pick_si(st.get('si'))          # 只认判得出格式的
                if not pick and st.get('suppPage'):
                    # ACS 不在文章页列文件，只给一个 /doi/suppl/<doi> 入口，
                    # 要再进一层才看得到（2026-09-06 实测）。
                    try:
                        page.goto(st['suppPage'], wait_until='domcontentloaded',
                                  timeout=timeout * 1000)
                        page.wait_for_timeout(settle * 1000)
                        pick = pick_si(page.evaluate(_JS_STATE).get('si'))
                    except Exception:
                        pass
                if not pick:
                    out['reason'] = 'no_si'
                    return out
                cands = [pick['url']]
                out['filename'] = _si_name(pick)
            else:
                cands = st.get('candidates') or []
                if not cands:
                    out['reason'] = ('no_access' if st.get('paywall')
                                     else 'no_pdf_link')
                    return out

            # **一个候选走完两趟，再换下一个** —— 顺序不是形式。
            # 早先写成「先把所有候选直取一遍，再把所有候选导航一遍」，
            # 结果排在后面的差候选靠「这一趟更容易」抢在了好候选前面：
            # Wiley 那篇的正文 PDF 直取会被阅读器包一层（不是 PDF、跳过），
            # 而补充材料是直链 PDF，直取就成 —— 于是**下回来的是 SI 不是正文**。
            # 文件大小正常、格式也对，错得毫无迹象（2026-09-05 实测中过）。
            # ⚠ `_worth_trying` 是**给正文候选用的**，它专门排除 SuppMat 这类词。
            # 拿它去滤 SI 候选，等于把 SI 自己滤没了（2026-09-06 实测：
            # Wiley 的 SI 直取明明成功了，却因为这一步被丢掉，报成 not_pdf）。
            queue = [c for c in cands
                     if (c.startswith('http') if kind == 'si' else _worth_trying(c))]
            tried = set()
            while queue and len(tried) < MAX_TRIES:
                cand = queue.pop(0)
                if cand in tried:
                    continue
                tried.add(cand)

                # 第一趟：直接取。RSC / Springer 这类 citation_pdf_url
                # 多半指的就是真身，同源时一次就成。
                got = page.evaluate(_JS_GRAB, cand)
                raw = _decode(got, 'si' if kind == 'si' else 'pdf')
                if got.get('tooBig'):
                    out['reason'], out['pdf_url'] = 'too_big', cand
                    return out
                if raw:
                    out.update(ok=True, reason='ok', pdf=raw, pdf_url=cand)
                    return out

                # 第二趟：**导航过去再同源取**（2026-09-05 实测才发现要这么干）。
                # Elsevier 的 /pdfft 不直接给 PDF，它先回一张 HTML 中转页，
                # 再自己跳一次校验（`?crasolve=1`），最后才落到
                # pdf.sciencedirectassets.com 上那个带签名的真身。
                # 这条链**只有真导航能走完** —— 四种办法实测过：
                #   - `fetch(pdfft)`                    → 中转页的 HTML
                #   - `context.request.get()`           → 403（没有浏览器指纹）
                #   - 普通 HTTP 取签名直链              → 403
                #   - 导航过去 + `fetch(location.href)` → ✅ 真身
                # 截响应也不行：Chrome 把 PDF 交给内置阅读器，
                # `response.body()` 只能拿到 348 字节的壳。
                # 导航还顺带解决跨域：`citation_pdf_url` 常在另一个子域上，
                # 直取会 CORS 失败，导航过去就没这问题。
                try:
                    page.goto(cand, wait_until='domcontentloaded',
                              timeout=timeout * 1000)
                except Exception:
                    pass    # 导航到 PDF 常抛 ERR_ABORTED，不代表失败
                page.wait_for_timeout(settle * 1000)
                got = page.evaluate(_JS_GRAB_HERE)
                raw = _decode(got, 'si' if kind == 'si' else 'pdf')
                if got.get('tooBig'):
                    out['reason'], out['pdf_url'] = 'too_big', cand
                    return out
                if raw:
                    out.update(ok=True, reason='ok', pdf=raw,
                               pdf_url=page.url or cand)
                    return out

                # 第三趟（只在取 SI 时）：**跨域文件用浏览器上下文的 request 取**。
                # Elsevier 的 SI 挂在另一个域（ars.els-cdn.com）上，
                # 从文章页 fetch 它会被 CORS 挡（实测 ok=False 连状态码都没有）；
                # 而导航过去只会触发下载、页面不变，所以前两趟都够不着。
                if kind == 'si':
                    raw = _via_request(ctx, cand)
                    if raw:
                        out.update(ok=True, reason='ok', pdf=raw, pdf_url=cand)
                        return out

                # 第四趟：**这一页要是个阅读器，真身多半嵌在它里面**。
                # 2026-09-05 实测：Wiley 的 `/doi/pdf/<DOI>` 是它自家的阅读器
                # 页面（HTML），里面一个 iframe 指向 `/doi/pdfdirect/<DOI>`，
                # 那个才是 application/pdf 的真身。
                # 与其给 Wiley 写死一条 URL 规则，不如把「页面里嵌着的东西」
                # 一律当作新候选 —— 别家用阅读器包 PDF 的也一并解决了，
                # 而且出版商改 URL 形式的时候这条不用跟着改。
                try:
                    for u in page.evaluate(_JS_EMBEDS):
                        if _worth_trying(u) and u not in tried:
                            queue.append(u)
                except Exception:
                    pass

            out['reason'] = 'not_pdf'
            return out
        finally:
            try:
                page.close()
            except Exception:
                pass
    finally:
        if pw is not None:
            try:
                pw.stop()
            except Exception:
                pass


DOI_RE = re.compile(r'^10\.\d{4,9}/\S+$')


def is_doi(s):
    """长得像不像一个 DOI —— 上层用来把用户输入里的杂物挑掉。"""
    return bool(DOI_RE.match((s or '').strip()))
