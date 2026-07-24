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
import os, json, time, zipfile, io, urllib.request
import urllib.parse as _up, http.client as _hc

BASE = 'https://mineru.net/api/v4'


class PDFParseError(Exception):
    pass


def _token():
    t = os.environ.get('MINERU_TOKEN')
    if not t:
        raise PDFParseError('未设置 MINERU_TOKEN 环境变量')
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
