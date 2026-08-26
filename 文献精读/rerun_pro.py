# -*- coding: utf-8 -*-
"""用 deepseek-v4-pro 重跑某篇已解析文献的精读（高质量版）。
从 zotero_work 里已解析的文献中选一篇，用pro重新生成精读。
用法: python rerun_pro.py            列出可重跑的文献
      python rerun_pro.py <序号>     用pro重跑该篇
"""
import os, sys, re, json, subprocess, urllib.request

# 【标准开头】项目根加入 import 路径 + 强制 UTF-8 输出（详见 docs/代码规范_标准脚本模板.md）
_ROOT = os.path.dirname(os.path.abspath(__file__))
while True:
    if os.path.isdir(os.path.join(_ROOT, 'modules')):
        break                      # 项目根特征：modules/ 目录只在根存在
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        break                      # 到盘符根，兜底
    _ROOT = parent
sys.path.insert(0, _ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from modules.cli import pos
from modules.config import get_key, need_site, get_site

_NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = _ROOT
WORK = os.path.join(ROOT, 'workflow_data', 'zotero_work')
SUMMARY = os.path.join(ROOT, 'workflow_data', 'summary')
DEEPREAD = os.path.join(SCRIPT_DIR, 'deepread_v4.py')
DEEPSEEK_KEY = get_key('DEEPSEEK_KEY')


def get_title(key):
    """从 Zotero 本地 API 取标题（美化显示）；取不到返回 key。"""
    try:
        uid = need_site('ZOTERO_USER_ID')
        req = urllib.request.Request(get_site('ZOTERO_API_HOST') + f'/api/users/{uid}/items/{key}',
            headers={'Zotero-Allowed-Request': 'true'})
        return json.loads(urllib.request.urlopen(req, timeout=8).read())['data'].get('title', key)
    except Exception:
        return key   # Zotero 未开/未配：标题显示退回 key，不影响主流程


def main():
    dirs = [d for d in os.listdir(WORK) if os.path.isdir(os.path.join(WORK, d))
            and os.path.exists(os.path.join(WORK, d, 'layout.json'))]
    dirs.sort()

    idx_raw = pos(0)
    if not idx_raw:
        print('=== 可用 pro 重跑的已解析文献 ===\n')
        for i, d in enumerate(dirs):
            print(f'  [{i+1}] {get_title(d)[:55]}')
        print('\n用法：python rerun_pro.py <序号>   例如 python rerun_pro.py 2')
        sys.exit(0)

    idx = int(idx_raw) - 1
    if idx < 0 or idx >= len(dirs):
        print('序号超范围'); sys.exit(1)
    key = dirs[idx]
    title = get_title(key)
    safe = re.sub(r'[^\w\-]', '_', title)[:40]
    out = os.path.join(SUMMARY, f'{safe}_{key}_精读_PRO.html')
    print(f'用 deepseek-v4-pro 重跑：{title[:50]}')
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    r = subprocess.run([sys.executable, DEEPREAD, os.path.join(WORK, key), out,
                        'deepseek', 'deepseek-v4-pro', DEEPSEEK_KEY],
                       encoding='utf-8', errors='replace', env=env, creationflags=_NOWIN)
    print(f'\n完成，输出：{out}' if r.returncode == 0 else '失败')


if __name__ == '__main__':
    main()
