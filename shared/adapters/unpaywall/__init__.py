# -*- coding: utf-8 -*-
"""unpaywall · 一个 DOI 有没有**合法的开放获取全文**（2026-09-16 建）。

**解决的真实问题**：取全文这条线最脆弱 —— 靠学校权限、靠出版商没封 IP、靠那个浏览器活着。
Unpaywall 收录了每篇论文在出版社 / 机构库 / 作者存档里的合法免费版本：先问它，
有就直接下，**不碰出版商、不占机构权限、零风控风险**。没有再走浏览器。

免费、不用注册，只要一个真实邮箱做身份标识（`UNPAYWALL_EMAIL`，本机设置）。
没填邮箱就当作「没有」（返回 None），调用方照常走别的路 —— 别因为它没配就拒绝取件。

对外接口：
  - lookup(doi)      → {'is_oa', 'pdf_url', 'version', 'host', 'license'} 或 None（没配邮箱 / 查不到 / 没 OA）
  - fetch_pdf(doi)   → (pdf_bytes, info) 或 (None, info)：查 + 下载 + 验是 PDF
  - to_info(record)  → 把 Unpaywall 的原始 JSON 摆成上面那个字典（纯函数，自测用）

`version`：publishedVersion（出版社正式版）/ acceptedManuscript（接收稿，排版不同但内容同）/
submittedVersion（投稿稿，慎用）。SI 通常不在 OA 版本里，还得单独去出版社取。

依赖：Python 标准库 + shared.kernel.config / errors / log。
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from shared.kernel import errors
from shared.kernel.log import get_logger

BASE = 'https://api.unpaywall.org/v2'
UA = 'literature-platform/1.0'
MAX_BYTES = 80 * 1024 * 1024
_log = get_logger('unpaywall')
_warned = {'email': False}


class UnpaywallError(errors.ExternalServiceError):
    """Unpaywall 查询失败（对方抖动，可重试）。"""


def email():
    try:
        from shared.kernel.config import get_site
        return (get_site('UNPAYWALL_EMAIL') or '').strip()
    except Exception:
        return ''


def to_info(rec):
    """Unpaywall 的一条记录 → 我们的字典。挑 `best_oa_location`；没有就 None。"""
    if not rec or not rec.get('is_oa'):
        return None
    loc = rec.get('best_oa_location') or {}
    url = loc.get('url_for_pdf') or ''
    if not url:
        # 有些只给落地页没给 PDF 直链：其它位置里找一个带直链的
        for l in rec.get('oa_locations') or []:
            if l.get('url_for_pdf'):
                loc, url = l, l['url_for_pdf']
                break
    if not url:
        return None
    return {'is_oa': True, 'pdf_url': url, 'version': loc.get('version') or '',
            'host': loc.get('host_type') or '', 'license': loc.get('license') or ''}


def lookup(doi, timeout=30):
    """一个 DOI → info 或 None。没配邮箱返回 None（只提醒一次）。"""
    em = email()
    if not em:
        if not _warned['email']:
            _log.info('没填 UNPAYWALL_EMAIL，跳过开放获取查询（控制面板里填一个真实邮箱即可）')
            _warned['email'] = True
        return None
    doi = (doi or '').strip().replace('https://doi.org/', '')
    if not doi:
        return None
    url = '%s/%s?email=%s' % (BASE, urllib.parse.quote(doi), urllib.parse.quote(em))
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return to_info(json.loads(r.read().decode('utf-8')))
    except urllib.error.HTTPError as e:
        if e.code in (404, 422):
            return None                      # 不在库里 / DOI 不合法：都不是「可重试」
        raise UnpaywallError(f'HTTP {e.code}') from e
    except Exception as e:
        raise UnpaywallError(f'{type(e).__name__}: {e}') from e


def fetch_pdf(doi, timeout=120):
    """查 + 下载 → (bytes, info)。不是 PDF（登录页 / HTML）返回 (None, info)。"""
    info = lookup(doi)
    if not info:
        return None, info
    req = urllib.request.Request(info['pdf_url'], headers={'User-Agent': UA, 'Accept': 'application/pdf,*/*'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(MAX_BYTES + 1)
    except Exception as e:
        _log.info('%s 开放版本下载失败：%s' % (doi, str(e)[:80]))
        return None, info
    if len(data) > MAX_BYTES or not data.lstrip()[:5].startswith(b'%PDF'):
        return None, info
    return data, info
