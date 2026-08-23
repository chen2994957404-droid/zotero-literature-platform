# -*- coding: utf-8 -*-
"""批量精读：对给定 key 列表，复用已有的 MineRU 解析结果（library/<key>/parsed/）
调 deepread_v4 生成中文图文精读 summary.html。解析结果与精抽共享，不重复解析。

模型：精读是「输出重」的活（9000字长文），默认用 deepseek-v4-flash 省钱。
用法:
  python deepread_batch.py KEY1 KEY2 ...
  python deepread_batch.py --file keys.txt
"""
import os, sys, subprocess, shutil

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

from modules.cli import opt, positionals, flag
from modules.config import get_key, get_model

_NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = _ROOT
LIBRARY = os.path.join(ROOT, 'workflow_data', 'library')
DEEPREAD = os.path.join(SCRIPT_DIR, 'deepread_v4.py')

PROVIDER = 'deepseek'
MODEL = get_model('DEEPREAD_MODEL')   # 精读输出重→flash；可在控制面板切换
KEY = get_key('DEEPSEEK_KEY')


def read_one(key, force=False):
    parsed = os.path.join(LIBRARY, key, 'parsed')
    if not os.path.exists(os.path.join(parsed, 'layout.json')):
        print(f'  [跳过] 无 parsed 解析结果（需先精抽/MineRU）'); return False
    out_html = os.path.join(LIBRARY, key, 'summary.html')
    if os.path.exists(out_html) and not force:
        print(f'  [复用] 已有 summary.html（--force 可强制重跑）'); return True
    if force and os.path.exists(out_html):
        # 重跑前备份旧的，万一新的更差还能还原（可逆是自主执行的前提）
        bak = out_html + '.bak'
        if not os.path.exists(bak):
            shutil.copy2(out_html, bak)
            print(f'  [备份] 旧版存为 summary.html.bak')
    # deepread_v4.py 的 DeepSeek key 靠命令行第5参传入，不读环境变量（应用侧变更记录·认知2）
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    r = subprocess.run([sys.executable, DEEPREAD, parsed, out_html, PROVIDER, MODEL, KEY],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, creationflags=_NOWIN)
    if os.path.exists(out_html):
        sz = round(os.path.getsize(out_html) / 1024)
        print(f'  [完成] summary.html {sz} KB'); return True
    print(f'  [失败] {r.stdout[-200:]} {r.stderr[-200:]}'); return False


def main():
    fp = opt('--file')
    if fp:
        keys = [l.strip() for l in open(fp, encoding='utf-8') if l.strip()]
    else:
        keys = positionals()
    force = flag('--force')
    print(f'批量精读 {len(keys)} 篇（模型 {MODEL}{"，强制重跑" if force else ""}）\n')
    ok = fail = 0
    for i, key in enumerate(keys, 1):
        print(f'[{i}/{len(keys)}] {key}')
        try:
            if read_one(key, force): ok += 1
            else: fail += 1
        except Exception as e:
            print(f'  [出错] {e}'); fail += 1
    print(f'\n完成：成功 {ok}，失败/跳过 {fail}')


if __name__ == '__main__':
    main()
