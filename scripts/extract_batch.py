# -*- coding: utf-8 -*-
"""批量精层抽取：对给定 key 列表，自动「有 full.md 就复用、没有先 MineRU 解析」再 DeepSeek 精抽。

补上了 extract_structured.py 缺的一环——缺 full.md 时不再跳过，而是复用精读线的
MineRU 解析（find_pdf 定位本地 PDF → mineru_parse 落地到 library/<key>/parsed/），
再走精层抽取。MineRU 有每日免费额度，解析零成本；解析结果与精读线共享，谁先跑谁生成。

用法:
  python extract_batch.py KEY1 KEY2 ...        # 抽指定 key
  python extract_batch.py --file keys.txt      # 从文件读 key（每行一个）
"""
import os, sys, json, re, subprocess, urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

LIBRARY = os.path.join(ROOT, 'workflow_data', 'library')
OUT_DIR = os.path.join(ROOT, 'workflow_data', 'structured')
MINERU_SCRIPT = os.path.join(SCRIPT_DIR, 'mineru_parse.py')

# Zotero 本地读 + 存储路径（与 zotero_watcher.py 一致）
ZOTERO_LOCAL = 'http://localhost:23119/api'
ZH = {'Zotero-Allowed-Request': 'true'}
USER_ID = '16078117'
STORAGE_DIR = r'D:\03_Software\Zetero\Zotero\storage'

# 复用精层抽取的核心
from extract_structured import (SYS, build_user_prompt, hierarchical_body,
                                deepseek_json, DEEPSEEK_MODEL)

# find_pdf 已收敛到基础件 modules/zotero_client（消除重复拷贝）
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))
from modules.zotero_client import find_pdf

def ensure_fullmd(key):
    """确保 library/<key>/parsed/full.md 存在：有则复用，无则调 MineRU 解析。返回 full.md 路径或 None。"""
    parsed = os.path.join(LIBRARY, key, 'parsed')
    md = os.path.join(parsed, 'full.md')
    if os.path.exists(md):
        print(f'  [复用] 已有 full.md'); return md
    pdf = find_pdf(key)
    if not pdf:
        print(f'  [跳过] Zotero 里找不到正文 PDF'); return None
    os.makedirs(parsed, exist_ok=True)
    print(f'  [MineRU] 解析 {os.path.basename(pdf)} ...')
    r = subprocess.run([sys.executable, MINERU_SCRIPT, pdf, parsed],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if not os.path.exists(md):
        print(f'  [MineRU失败] {r.stdout[-200:]} {r.stderr[-200:]}'); return None
    print(f'  [MineRU完成] full.md 已生成'); return md

def extract_one(key):
    md = ensure_fullmd(key)
    if not md: return False
    meta_path = os.path.join(LIBRARY, key, 'meta.json')
    meta = json.load(open(meta_path, encoding='utf-8')) if os.path.exists(meta_path) else {}
    title = meta.get('title', key)
    body = hierarchical_body(open(md, encoding='utf-8').read())
    print(f'  [精抽] DeepSeek {DEEPSEEK_MODEL} ...')
    data = deepseek_json(SYS, build_user_prompt(title, body))
    record = {'key': key, 'title': title, 'doi': meta.get('DOI', ''), **data}  # 无 source=精层，受#16保护
    json.dump(record, open(os.path.join(OUT_DIR, f'{key}.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    kp = record.get('key_properties')
    print(f'  [完成] key_properties: {str(kp)[:70]}')
    return True

def main():
    if '--file' in sys.argv:
        fp = sys.argv[sys.argv.index('--file') + 1]
        keys = [l.strip() for l in open(fp, encoding='utf-8') if l.strip()]
    else:
        keys = [a for a in sys.argv[1:] if not a.startswith('--')]
    print(f'批量精层抽取 {len(keys)} 篇\n')
    ok = fail = 0
    for i, key in enumerate(keys, 1):
        print(f'[{i}/{len(keys)}] {key}')
        try:
            if extract_one(key): ok += 1
            else: fail += 1
        except Exception as e:
            print(f'  [出错] {e}'); fail += 1
    print(f'\n完成：成功 {ok}，失败/跳过 {fail}')

if __name__ == '__main__':
    main()
