# -*- coding: utf-8 -*-
"""新文献自动入库（定时任务调用，每小时一次）

解决缺口：以前只有"精读"是自动的（打标签触发），而**向量化和结构化抽取都要手动跑**，
导致用户在 Zotero 加了文献后，问答（查向量库）和对比表（查 structured）都看不到新文献。

本脚本做两件事，都是**增量**（已处理的跳过，没新文献时几秒结束）：
  1. 增量向量化   → vectorize_library.py（走 Zotero 全文API，本地 bge-m3，零成本）
  2. 增量粗层抽取 → extract_library.py（本地 qwen，零成本；精层记录受保护不覆盖）

前提：Zotero 开着（取全文）+ Ollama 在跑（向量化/本地抽取）。两者都有保活任务。
用法: python auto_sync.py        （由任务计划 LiteratureAutoSync 每小时调用）
"""
import os, sys, subprocess, time, io, json, urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
LOG = os.path.join(ROOT, 'workflow_data', 'logs', 'auto_sync.log')
os.makedirs(os.path.dirname(LOG), exist_ok=True)


def log(msg):
    line = f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}'
    print(line)
    try:
        with io.open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def _alive(url, headers=None, timeout=6):
    try:
        urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=timeout)
        return True
    except Exception:
        return False


def check_deps():
    """检查依赖服务。缺了就跳过本轮（下轮再来），不报错刷屏。"""
    zot = _alive('http://localhost:23119/api/users/16078117/items/top?limit=1',
                 {'Zotero-Allowed-Request': 'true'})
    olla = _alive('http://localhost:11434/api/tags')
    if not zot:
        log('跳过本轮：Zotero 未开（取不到全文）'); return False
    if not olla:
        log('跳过本轮：Ollama 未跑（无法向量化）'); return False
    return True


def run(script, name, timeout=3600):
    """跑一个增量脚本，返回是否成功。"""
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    try:
        r = subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, script)],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', env=env, timeout=timeout, cwd=ROOT)
        tail = (r.stdout or '').strip().splitlines()
        summary = tail[-1] if tail else '(无输出)'
        log(f'{name}: {summary}')
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        log(f'{name}: 超时（{timeout}s），下轮继续'); return False
    except Exception as e:
        log(f'{name}: 出错 {e}'); return False


def main():
    log('=== 自动同步开始 ===')
    if not check_deps():
        return
    # 1. 增量向量化（新文献进向量库 → 问答能查到）
    run('vectorize_library.py', '增量向量化')
    # 2. 增量粗层结构化抽取（新文献进对比表 → 横向比较能看到）
    run('extract_library.py', '增量粗层抽取')
    log('=== 自动同步结束 ===')


if __name__ == '__main__':
    main()
