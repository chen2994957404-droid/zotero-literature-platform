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
import os, sys, time, io, json, urllib.request
from subprocess import TimeoutExpired

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from core import paths
from core.paths import ROOT as _ROOT

from modules.config import need_site, get_site
from modules.subproc import run as _sub_run   # 子进程统一走积木：不弹窗+超时+UTF-8

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG = paths.log('auto_sync')
os.makedirs(os.path.dirname(LOG), exist_ok=True)


def log(msg):
    line = f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}'
    print(line)
    try:
        with io.open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass  # 日志落盘失败只丢这一条，print 已成功，不影响主流程


def _alive(url, headers=None, timeout=6):
    try:
        urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=timeout)
        return True
    except Exception:
        return False  # 探活失败=服务没开，属正常分支，由调用方决定拉起或跳过


def _revive(task_name, disp, probe_url, headers=None, wait=30):
    """依赖服务没在跑 → 通过任务计划拉起来，再探活确认。返回是否活过来了。

    只拉起、不杀进程，是可逆的安全操作，所以可以自动做，不必打扰用户。
    """
    log(f'{disp} 未响应，尝试拉起…')
    try:
        _sub_run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                  f'Start-ScheduledTask -TaskName {task_name}'], timeout=40)
    except Exception as e:
        log(f'{disp} 拉起失败: {e}')
        return False
    for _ in range(wait // 5):          # 给它时间起来，别急着判死
        time.sleep(5)
        if _alive(probe_url, headers):
            log(f'{disp} 已恢复')
            return True
    log(f'{disp} 拉起后仍未响应')
    return False


def check_deps():
    """检查依赖服务。缺了就跳过本轮（下轮再来），不报错刷屏。"""
    # 本机配置（Zotero 用户ID / 附件目录）统一从 modules.config 读，换电脑只改 .env
    _UID = need_site('ZOTERO_USER_ID')
    _STORAGE = need_site('ZOTERO_STORAGE')
    zot = _alive(get_site('ZOTERO_API_HOST') + f'/api/users/{_UID}/items/top?limit=1',
                 {'Zotero-Allowed-Request': 'true'})
    olla = _alive(get_site('OLLAMA_HOST') + '/api/tags')

    # 依赖挂了就尝试拉起来，而不是干等下一轮（踩坑 #33）。
    # 之前只「跳过」，结果 Zotero 开机没起来后就一直没人管，
    # 精读线静默停摆了 19 分钟用户才发现。**保活任务就该负责保活。**
    if not zot:
        zot = _revive('ZoteroApp', 'Zotero',
                      get_site('ZOTERO_API_HOST') + f'/api/users/{_UID}/items/top?limit=1',
                      {'Zotero-Allowed-Request': 'true'})
    if not olla:
        olla = _revive('OllamaService', 'Ollama', get_site('OLLAMA_HOST') + '/api/tags')

    if not zot:
        log('跳过本轮：Zotero 未开且拉起失败（取不到全文）'); return False
    if not olla:
        log('跳过本轮：Ollama 未跑且拉起失败（无法向量化）'); return False
    return True


def run(script, name, timeout=3600):
    """跑一个增量脚本，返回是否成功。"""
    try:
        r = _sub_run([sys.executable, os.path.join(SCRIPT_DIR, script)],
                     timeout=timeout, cwd=_ROOT,
                     env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        tail = (r.stdout or '').strip().splitlines()
        summary = tail[-1] if tail else '(无输出)'
        log(f'{name}: {summary}')
        return r.returncode == 0
    except TimeoutExpired:
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
