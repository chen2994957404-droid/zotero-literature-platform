# -*- coding: utf-8 -*-
"""批量精读：对给定 key 列表，复用已有的 MineRU 解析结果（library/<key>/parsed/）
调 deepread_v4 生成中文图文精读 summary.html。解析结果与精抽共享，不重复解析。

模型：精读是「输出重」的活（9000字长文），默认用 deepseek-v4-flash 省钱。
用法:
  python deepread_batch.py KEY1 KEY2 ...
  python deepread_batch.py --file keys.txt
"""
import os, sys, subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
LIBRARY = os.path.join(ROOT, 'workflow_data', 'library')
DEEPREAD = os.path.join(SCRIPT_DIR, 'deepread_v4.py')

PROVIDER = 'deepseek'
MODEL = os.environ.get('DEEPREAD_MODEL', 'deepseek-v4-flash')  # 精读输出重→flash
KEY = os.environ.get('DEEPSEEK_KEY', '')

def read_one(key):
    parsed = os.path.join(LIBRARY, key, 'parsed')
    if not os.path.exists(os.path.join(parsed, 'layout.json')):
        print(f'  [跳过] 无 parsed 解析结果（需先精抽/MineRU）'); return False
    out_html = os.path.join(LIBRARY, key, 'summary.html')
    if os.path.exists(out_html):
        print(f'  [复用] 已有 summary.html'); return True
    # deepread_v4.py 的 DeepSeek key 靠命令行第5参传入，不读环境变量（应用侧变更记录·认知2）
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    r = subprocess.run([sys.executable, DEEPREAD, parsed, out_html, PROVIDER, MODEL, KEY],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
    if os.path.exists(out_html):
        sz = round(os.path.getsize(out_html) / 1024)
        print(f'  [完成] summary.html {sz} KB'); return True
    print(f'  [失败] {r.stdout[-200:]} {r.stderr[-200:]}'); return False

def main():
    if '--file' in sys.argv:
        fp = sys.argv[sys.argv.index('--file') + 1]
        keys = [l.strip() for l in open(fp, encoding='utf-8') if l.strip()]
    else:
        keys = [a for a in sys.argv[1:] if not a.startswith('--')]
    print(f'批量精读 {len(keys)} 篇（模型 {MODEL}）\n')
    ok = fail = 0
    for i, key in enumerate(keys, 1):
        print(f'[{i}/{len(keys)}] {key}')
        try:
            if read_one(key): ok += 1
            else: fail += 1
        except Exception as e:
            print(f'  [出错] {e}'); fail += 1
    print(f'\n完成：成功 {ok}，失败/跳过 {fail}')

if __name__ == '__main__':
    main()
