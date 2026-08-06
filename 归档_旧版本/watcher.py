# -*- coding: utf-8 -*-
"""宿主机守护脚本：监听 to_process 目录，发现新的 MineRU 解析结果就生成精读HTML。
n8n 负责把每篇文献的解析结果（layout.json + origin.pdf + full.md + images/）
解压到 to_process/<任务ID>/ 下，并放一个 .ready 标记文件。
本脚本轮询，处理完移到 done/，精读HTML输出到 summary/。
运行: python watcher.py
"""
import os, time, subprocess, shutil, sys, traceback
try:
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
    from modules.config import get_key as _cfg_get
except Exception:
    _cfg_get = lambda n, **kw: _o.environ.get(n, '')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)  # 项目根目录（scripts的上一级）
WORKDIR = os.path.join(ROOT, 'workflow_data')
TO_PROCESS = os.path.join(WORKDIR, 'to_process')
DONE = os.path.join(WORKDIR, 'done')
SUMMARY = os.path.join(WORKDIR, 'summary')
DEEPREAD = os.path.join(SCRIPT_DIR, 'deepread_v4.py')

# 配置（可改）
PROVIDER = os.environ.get('DEEPREAD_PROVIDER', 'deepseek')
MODEL = os.environ.get('DEEPREAD_MODEL', 'deepseek-v4-pro')
DEEPSEEK_KEY = _cfg_get('DEEPSEEK_KEY')

for d in (TO_PROCESS, DONE, SUMMARY):
    os.makedirs(d, exist_ok=True)

def process(task_dir, name):
    # 校验必需文件
    files = os.listdir(task_dir)
    has_layout = any(f == 'layout.json' for f in files)
    has_pdf = any(f.endswith('origin.pdf') for f in files)
    has_md = any(f.endswith('.md') for f in files)
    if not (has_layout and has_pdf and has_md):
        print(f'[跳过] {name}: 缺文件 layout={has_layout} pdf={has_pdf} md={has_md}')
        return False
    out_html = os.path.join(SUMMARY, name + '_精读.html')
    print(f'[处理] {name} -> {out_html}')
    cmd = [sys.executable, DEEPREAD, task_dir, out_html, PROVIDER, MODEL, DEEPSEEK_KEY]
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=900, env=env)
    print(r.stdout)
    if r.returncode != 0:
        print(f'[失败] {name}:\n{r.stderr}')
        return False
    print(f'[完成] {name}')
    return True

def main():
    print('精读守护脚本已启动，监听:', TO_PROCESS)
    print(f'引擎: {PROVIDER}/{MODEL}')
    while True:
        try:
            for name in os.listdir(TO_PROCESS):
                task_dir = os.path.join(TO_PROCESS, name)
                if not os.path.isdir(task_dir):
                    continue
                # 需要 .ready 标记，确保 n8n 写完了
                if not os.path.exists(os.path.join(task_dir, '.ready')):
                    continue
                ok = False
                try:
                    ok = process(task_dir, name)
                except Exception:
                    traceback.print_exc()
                # 处理完（无论成败）移到 done，避免重复处理
                dest = os.path.join(DONE, name + '_' + time.strftime('%H%M%S'))
                try:
                    shutil.move(task_dir, dest)
                except Exception:
                    pass
        except Exception:
            traceback.print_exc()
        time.sleep(5)

if __name__ == '__main__':
    main()
