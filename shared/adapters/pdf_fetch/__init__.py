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

# fetch 的 reason 取值 —— 每一种的处置都不同，别合并
REASONS = {
    'ok': '拿到了',
    'captcha': '撞上人机验证 —— 要人在那个浏览器里点一下，之后同一浏览器会顺畅一阵',
    'no_access': '页面在，但没有全文权限（这本刊学校没订，或者当前出口 IP 不是机构）',
    'no_pdf_link': '页面在、也像有权限，但找不到 PDF 直链（多半是这家出版商的页面改版了）',
    'not_pdf': '拿到了东西但不是 PDF（多半被挡回了登录页或验证页）',
    'too_big': '文件超过上限，没往回传',
    'navigate_failed': '页面根本打不开',
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
  const hits = [];
  if (meta && meta.content) hits.push(meta.content);
  for (const s of sels) {
    const a = document.querySelector(s);
    if (a && a.href) hits.push(a.href);
  }
  return {
    url: location.href,
    title: (document.querySelector('h1') || {}).innerText || document.title || '',
    captcha: has('Are you a robot') ||
             (has('Just a moment') && t.toLowerCase().indexOf('checking') >= 0),
    paywall: has('Get Access') || has('Purchase PDF') || has('Get rights and content')
             && !hits.length,
    candidates: hits,
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


def pdf_url_of(page):
    """当前页面上的 PDF 直链候选（按可信度排序）。排查时单独用得上。"""
    return page.evaluate(_JS_STATE).get('candidates') or []


def _looks_like_pdf(head, mime):
    """PDF 的magic number 是 %PDF —— 比 MIME 可信，出版商常把类型写错。"""
    return head[:4] == b'%PDF' or 'pdf' in (mime or '')


def fetch(doi, url=None, timeout=90, settle=6):
    """一个 DOI → dict(ok, reason, pdf, landing, title, pdf_url)。

    `settle` 是落地后多等几秒：出版商页面普遍是前端渲染，
    `domcontentloaded` 时 PDF 链接还没长出来。宁可多等，重试更贵。
    """
    sync_playwright = _sync_api()
    out = {'ok': False, 'reason': 'navigate_failed', 'doi': doi,
           'pdf': b'', 'landing': '', 'title': '', 'pdf_url': ''}
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
            cands = st.get('candidates') or []
            if not cands:
                out['reason'] = 'no_access' if st.get('paywall') else 'no_pdf_link'
                return out

            for cand in cands:
                got = page.evaluate(_JS_GRAB, cand)
                if got.get('tooBig'):
                    out['reason'], out['pdf_url'] = 'too_big', cand
                    return out
                if not got.get('ok'):
                    continue
                raw = base64.b64decode(got['b64'])
                if _looks_like_pdf(raw[:4], got.get('type')):
                    out.update(ok=True, reason='ok', pdf=raw, pdf_url=cand)
                    return out
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
