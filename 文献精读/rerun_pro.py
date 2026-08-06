# -*- coding: utf-8 -*-
"""用 deepseek-v4-pro 重跑某篇已解析文献的精读（高质量版）。
从 zotero_work 里已解析的文献中选一篇，用pro重新生成精读。
用法: python rerun_pro.py            列出可重跑的文献
      python rerun_pro.py <序号>     用pro重跑该篇
"""
import os, sys, subprocess, urllib.request, json
_NOWIN = getattr(__import__('subprocess'), 'CREATE_NO_WINDOW', 0) if __import__('os').name == 'nt' else 0
try:
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
    from modules.config import get_key as _cfg_get
except Exception:
    _cfg_get = lambda n, **kw: _o.environ.get(n, '')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
WORK = os.path.join(ROOT, 'workflow_data', 'zotero_work')
SUMMARY = os.path.join(ROOT, 'workflow_data', 'summary')
DEEPREAD = os.path.join(SCRIPT_DIR, 'deepread_v4.py')
DEEPSEEK_KEY = _cfg_get('DEEPSEEK_KEY')

# 从Zotero本地API取标题（美化显示）
def get_title(key):
    try:
        # 本机配置（Zotero 用户ID / 附件目录）统一从 modules.config 读，换电脑只改 .env
        import os as _os, sys as _sys
        _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        try:
            from modules.config import need_site as _site
        except Exception:
            _site = lambda n: _os.environ.get(n) or (_ for _ in ()).throw(RuntimeError(f'缺少本机设置 {n}，请在控制面板或 .env 中配置'))
        _UID = _site('ZOTERO_USER_ID')
        _STORAGE = _site('ZOTERO_STORAGE')
        req = urllib.request.Request(f'http://localhost:23119/api/users/{_UID}/items/{key}',
            headers={'Zotero-Allowed-Request': 'true'})
        return json.loads(urllib.request.urlopen(req, timeout=8).read())['data'].get('title', key)
    except Exception:
        return key

dirs = [d for d in os.listdir(WORK) if os.path.isdir(os.path.join(WORK, d))
        and os.path.exists(os.path.join(WORK, d, 'layout.json'))]
dirs.sort()

if len(sys.argv) < 2:
    print('=== 可用 pro 重跑的已解析文献 ===\n')
    for i, d in enumerate(dirs):
        print(f'  [{i+1}] {get_title(d)[:55]}')
    print('\n用法：python rerun_pro.py <序号>   例如 python rerun_pro.py 2')
    sys.exit(0)

idx = int(sys.argv[1]) - 1
if idx < 0 or idx >= len(dirs):
    print('序号超范围'); sys.exit(1)
key = dirs[idx]
title = get_title(key)
import re
safe = re.sub(r'[^\w\-]', '_', title)[:40]
out = os.path.join(SUMMARY, f'{safe}_{key}_精读_PRO.html')
print(f'用 deepseek-v4-pro 重跑：{title[:50]}')
env = dict(os.environ, PYTHONIOENCODING='utf-8')
r = subprocess.run([sys.executable, DEEPREAD, os.path.join(WORK, key), out,
                    'deepseek', 'deepseek-v4-pro', DEEPSEEK_KEY],
                   encoding='utf-8', errors='replace', env=env, creationflags=_NOWIN)
print(f'\n完成，输出：{out}' if r.returncode == 0 else '失败')
