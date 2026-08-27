# -*- coding: utf-8 -*-
"""独立 MineRU 解析脚本：本地PDF -> 调MineRU API -> 解压结果到输出目录。

用法: python mineru_parse.py <pdf_path> <output_dir>
输出目录含 layout.json / *_origin.pdf / full.md / images/

**结构约定（踩坑 #34）**：所有有副作用的代码都必须在 main() 里，
模块顶层只允许定义常量与函数。原因：体检的运行时导入检查会加载本文件，
若副作用写在顶层，检查一跑就会真的建目录、甚至真的调用付费 API。
**检查工具不该有副作用；能被安全 import，是脚本的基本素养。**
"""
import os, sys, json, time, zipfile, io, urllib.request

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from core.cli import pos
from core.config import get_key   # 密钥统一从 core/config 读（环境变量 → 系统凭据库 → .env）

BASE = 'https://mineru.net/api/v4'


def api(path, method='GET', body=None, token=None):
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method,
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def parse(pdf_path, out_dir, token=None):
    """把一个 PDF 送去 MineRU 解析，结果解压到 out_dir。"""
    token = token or get_key('MINERU_TOKEN')
    if not token:
        raise SystemExit('缺少 MINERU_TOKEN，请在控制面板里填写')
    os.makedirs(out_dir, exist_ok=True)

    # 1. 申请上传地址
    fname = os.path.basename(pdf_path)
    r = api('/file-urls/batch', 'POST', {
        "enable_formula": True, "enable_table": True, "language": "en",
        "model_version": "vlm",
        "files": [{"name": fname, "is_ocr": True,
                   "data_id": "zot_" + str(int(time.time()))}]}, token=token)
    batch_id = r['data']['batch_id']
    upload_url = r['data']['file_urls'][0]
    print(f'batch_id={batch_id}')

    # 2. PUT 上传。用 http.client 直连以完全控制请求头 ——
    #    **不能发 Content-Type**，否则与 OSS 的签名不匹配会被拒。
    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()
    import urllib.parse as _up, http.client as _hc
    u = _up.urlparse(upload_url)
    conn = _hc.HTTPSConnection(u.netloc, timeout=180)
    conn.request('PUT', u.path + '?' + u.query, body=pdf_bytes, headers={})
    resp = conn.getresponse()
    resp.read()
    if resp.status not in (200, 201):
        raise SystemExit(f'上传失败 HTTP {resp.status}')
    conn.close()
    print('上传完成')

    # 3. 轮询结果
    zip_url = None
    for _ in range(40):
        time.sleep(8)
        r = api(f'/extract-results/batch/{batch_id}', token=token)
        st = r['data']['extract_result'][0]['state']
        if st == 'done':
            zip_url = r['data']['extract_result'][0]['full_zip_url']
            print('解析完成')
            break
        if st == 'failed':
            raise SystemExit('解析失败: ' + r['data']['extract_result'][0].get('err_msg', ''))
    if not zip_url:
        raise SystemExit('解析超时')

    # 4. 下载并解压
    zip_bytes = urllib.request.urlopen(zip_url, timeout=120).read()
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    z.extractall(out_dir)
    print(f'已解压到 {out_dir}，文件数 {len(z.namelist())}')
    return out_dir


def main():
    pdf_path, out_dir = pos(0), pos(1)
    if not (pdf_path and out_dir):
        print(__doc__)
        raise SystemExit(2)
    parse(pdf_path, out_dir)


if __name__ == '__main__':
    main()
