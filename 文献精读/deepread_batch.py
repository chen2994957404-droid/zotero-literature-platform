# -*- coding: utf-8 -*-
"""批量精读：对给定 key 列表，复用已有的 MineRU 解析结果（library/<key>/parsed/）
调 pipelines.deepread 的正文精读生成 summary.html。解析结果与精抽共享，不重复解析。

模型：精读是「输出重」的活（9000字长文），默认用 deepseek-v4-flash 省钱。
用法:
  python deepread_batch.py KEY1 KEY2 ...
  python deepread_batch.py --file keys.txt
"""
import os, sys, shutil

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from core import paths, role
from core.paths import ROOT as _ROOT

from core.cli import opt, positionals, flag
from core.config import get_key, get_model
from core import jobs
from pipelines import deepread
from pipelines.deepread import main_text

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = _ROOT
LIBRARY = paths.LIBRARY

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
    # 阶段 3 起直接调函数，不再拉子进程 —— 失败拿得到原因，不只是退出码。
    # 每次执行都记进 core.jobs（哪个模型、哪版提示词、失败原因）。
    with jobs.track(key, deepread.STEP_MAIN, producer=main_text.PRODUCER,
                    model=MODEL, prompt_ver=main_text.PROMPT_VER):
        main_text.read_main(parsed, out_html, provider=PROVIDER, model=MODEL, key=KEY)
    sz = round(os.path.getsize(out_html) / 1024)
    print(f'  [完成] summary.html {sz} KB'); return True


def main():
    # 机器角色守卫：这件事只允许在运行端（主力机）做，见 docs/两台机器的分工.md
    role.require_prod('批量精读（调用付费 API）', force=flag('--force'))
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
