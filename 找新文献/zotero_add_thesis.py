# -*- coding: utf-8 -*-
"""为毕业论文孤儿附件创建 thesis 条目并挂载附件、归入分类。"""
import urllib.request, json, os, fitz, time
try:
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
    from modules.config import get_key as _cfg_get
except Exception:
    _cfg_get = lambda n, **kw: _o.environ.get(n, '')

# 本机配置（Zotero 用户ID / 附件目录）统一从 modules.config 读，换电脑只改 .env
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
try:
    from modules.config import need_site as _site
except Exception:
    _site = lambda n: _os.environ.get(n) or (_ for _ in ()).throw(RuntimeError(f'缺少本机设置 {n}，请在控制面板或 .env 中配置'))
_UID = _site('ZOTERO_USER_ID')
_STORAGE = _site('ZOTERO_STORAGE')
USER_ID=_UID; KEY=_cfg_get('ZOTERO_API_KEY')
WEB='https://api.zotero.org/users/'+USER_ID
WH={'Zotero-API-Key':KEY,'Zotero-API-Version':'3','Content-Type':'application/json'}
STORAGE=_STORAGE
THESIS_COLLECTION='8X73UY35'  # 毕业论文分类

# 手动确认的元数据（从PDF首页读出）
THESES = [
  {'att_key':'FHQ9NNA2',
   'title':'基于含水动态硬性母材的自修复凝胶的设计与制备研究',
   'author_last':'郭','author_first':'华','year':'2025','univ':'四川大学','type':'博士学位论文'},
  {'att_key':'PXP4AQVC',
   'title':'基于动态化学的糖响应高分子的制备研究',
   'author_last':'阿其他','author_first':'','year':'2021','univ':'四川大学','type':'博士学位论文'},
]

def web(path, method='GET', body=None):
    data=json.dumps(body).encode('utf-8') if body is not None else None
    req=urllib.request.Request(WEB+path, data=data, method=method, headers=WH)
    return json.loads(urllib.request.urlopen(req, timeout=20).read())

def get_ver(key):
    return web('/items/'+key)['version']

for t in THESES:
    # 1. 创建 thesis 条目
    creators=[]
    if t['author_last']:
        creators=[{'creatorType':'author','lastName':t['author_last'],'firstName':t['author_first']}]
    item=[{
        'itemType':'thesis',
        'title':t['title'],
        'creators':creators,
        'thesisType':t['type'],
        'university':t['univ'],
        'date':t['year'],
        'collections':[THESIS_COLLECTION],
    }]
    r=web('/items','POST',item)
    new_key=r['successful']['0']['key']
    print(f"创建条目 {new_key}: {t['title'][:30]}")
    time.sleep(1)
    # 2. 把孤儿附件挂到新条目下（改 parentItem，同时归入分类）
    att_key=t['att_key']
    ver=get_ver(att_key)
    patch={'parentItem':new_key}
    req=urllib.request.Request(WEB+'/items/'+att_key, data=json.dumps(patch).encode(),
        method='PATCH', headers={**WH,'If-Unmodified-Since-Version':str(ver)})
    urllib.request.urlopen(req,timeout=20)
    print(f"  附件 {att_key} 已挂到 {new_key}，命名Full Text PDF")
    # 附件改名为 Full Text PDF
    time.sleep(1)
    ver=get_ver(att_key)
    req=urllib.request.Request(WEB+'/items/'+att_key, data=json.dumps({'title':'Full Text PDF'}).encode(),
        method='PATCH', headers={**WH,'If-Unmodified-Since-Version':str(ver)})
    urllib.request.urlopen(req,timeout=20)
    time.sleep(1)
print('完成')
