# -*- coding: utf-8 -*-
"""pdf_parse · PDF 解析基础件（公理：PDF → 结构化文本+图坐标）

职责：把一个 PDF 解析成 full.md（全文）+ layout.json（版面/图坐标）+ images/ + 原PDF副本。
这是「公理层」的一块——精读/结构化抽取/向量化三条定理都依赖它。
底层用 MineRU 云端 API（VLM 模型，处理公式/表格/版面）。

公理特征：只做「PDF→解析结果」这一件不可再分的事，不依赖任何上层模块。

对外接口：
  - parse_pdf(pdf_path, out_dir) → out_dir（含 full.md/layout.json/images/*_origin.pdf）
                                    已解析过（out_dir 有 layout.json）则直接复用，省 MineRU。

配置（环境变量）：
  - MINERU_TOKEN : MineRU API token（必须；无默认，密钥不硬编码）
"""
import os, json, time, zipfile, io, urllib.request, urllib.error
import urllib.parse as _up, http.client as _hc

BASE = 'https://mineru.net/api/v4'


class PDFParseError(Exception):
    pass


def _token():
    """取 MineRU token：走 config 公理件（环境变量 → .env），避免子进程拿不到。"""
    t = os.environ.get('MINERU_TOKEN')
    if not t:
        try:
            import sys as _s
            _s.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            from core.config import get_key
            t = get_key('MINERU_TOKEN')
        except Exception:
            t = ''
    if not t:
        raise PDFParseError(
            '未找到 MINERU_TOKEN。请在项目根 .env 写 MINERU_TOKEN=你的token，'
            '或设环境变量后重启进程')
    return t


def _api(path, method='GET', body=None):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
        headers={'Authorization': f'Bearer {_token()}', 'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def is_parsed(out_dir):
    """out_dir 是否已有解析结果（layout.json 存在即视为已解析）。"""
    return os.path.exists(os.path.join(out_dir, 'layout.json'))


def parse_pdf(pdf_path, out_dir, reuse=True):
    """解析 PDF 到 out_dir。已解析过且 reuse=True 则直接复用（省 MineRU 额度）。

    产出：out_dir/{full.md, layout.json, *_origin.pdf, images/}。返回 out_dir。
    """
    os.makedirs(out_dir, exist_ok=True)
    if reuse and is_parsed(out_dir):
        return out_dir

    fname = os.path.basename(pdf_path)
    # 1. 申请上传地址
    r = _api('/file-urls/batch', 'POST', {
        "enable_formula": True, "enable_table": True, "language": "en", "model_version": "vlm",
        "files": [{"name": fname, "is_ocr": True, "data_id": "zot_" + str(int(time.time()))}]})
    batch_id = r['data']['batch_id']
    upload_url = r['data']['file_urls'][0]

    # 2. PUT 上传（无 Content-Type 头，避免 OSS 签名不匹配 —— 踩坑 #1）
    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()
    u = _up.urlparse(upload_url)
    conn = _hc.HTTPSConnection(u.netloc, timeout=180)
    conn.request('PUT', u.path + '?' + u.query, body=pdf_bytes, headers={})
    resp = conn.getresponse(); resp.read()
    status = resp.status; conn.close()
    if status not in (200, 201):
        raise PDFParseError(f'上传失败 HTTP {status}')

    # 3. 轮询（字段结构见踩坑 #2）
    zip_url = None
    for _ in range(40):
        time.sleep(8)
        r = _api(f'/extract-results/batch/{batch_id}')
        res = r['data']['extract_result'][0]
        st = res['state']
        if st == 'done':
            zip_url = res['full_zip_url']; break
        if st == 'failed':
            raise PDFParseError('解析失败: ' + res.get('err_msg', ''))
    if not zip_url:
        raise PDFParseError('解析超时')

    # 4. 下载解压
    zip_bytes = urllib.request.urlopen(zip_url, timeout=120).read()
    zipfile.ZipFile(io.BytesIO(zip_bytes)).extractall(out_dir)
    return out_dir


def check_token(timeout=20):
    """MineRU token 还有效吗？返回 (ok, 说明)。**零成本，不产生解析任务**。

    做法：拿一个不存在的 batch id 去查结果 ——
      · token 有效 → HTTP 200 + `task not found or expire`（业务层说找不到）
      · token 无效 → HTTP 401 `user authenticate failed`
    实测确认过两种响应（2026-08-28）。这是目前找到的唯一免费校验方式：
    MineRU 没有「查账号/查额度」这类接口。
    """
    try:
        tok = _token()
    except PDFParseError as e:
        return False, str(e)[:60]
    req = urllib.request.Request(
        BASE + '/extract-results/batch/zzzznotexist',
        headers={'Authorization': 'Bearer ' + tok})
    try:
        urllib.request.urlopen(req, timeout=timeout)
        return True, '有效'
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, 'token 无效或已过期，去 mineru.net 重新申请'
        return None, f'查不了：HTTP {e.code}'
    except Exception as e:
        return None, f'连不上 MineRU：{type(e).__name__}'
