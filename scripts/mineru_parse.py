# -*- coding: utf-8 -*-
"""独立 MineRU 解析脚本：本地PDF -> 调MineRU API -> 解压结果到输出目录。
用法: python mineru_parse.py <pdf_path> <output_dir>
输出目录含 layout.json / *_origin.pdf / full.md / images/
"""
import sys, os, json, time, zipfile, io, urllib.request

# 密钥统一从 modules/config 读（环境变量 → .env），必须在使用前定义
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from modules.config import get_key as _cfg_get
except Exception:
    _cfg_get = lambda n, **kw: os.environ.get(n, '')

PDF_PATH, OUT_DIR = sys.argv[1], sys.argv[2]
TOKEN = _cfg_get('MINERU_TOKEN')
BASE = 'https://mineru.net/api/v4'
os.makedirs(OUT_DIR, exist_ok=True)

def api(path, method='GET', body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method,
        headers={'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

# 1. 申请上传地址
fname = os.path.basename(PDF_PATH)
r = api('/file-urls/batch', 'POST', {
    "enable_formula": True, "enable_table": True, "language": "en", "model_version": "vlm",
    "files": [{"name": fname, "is_ocr": True, "data_id": "zot_" + str(int(time.time()))}]})
batch_id = r['data']['batch_id']
upload_url = r['data']['file_urls'][0]
print(f'batch_id={batch_id}')

# 2. PUT 上传（无 Content-Type 头，避免OSS签名不匹配）
with open(PDF_PATH, 'rb') as f:
    pdf_bytes = f.read()
# 用 http.client 直连，完全控制请求头（不发 Content-Type，避免OSS签名不匹配）
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

# 3. 轮询
zip_url = None
for i in range(40):
    time.sleep(8)
    r = api(f'/extract-results/batch/{batch_id}')
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
z.extractall(OUT_DIR)
print(f'已解压到 {OUT_DIR}，文件数 {len(z.namelist())}')
