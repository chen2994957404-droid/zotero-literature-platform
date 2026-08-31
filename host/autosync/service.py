# -*- coding: utf-8 -*-
"""新文献自动入库（定时任务调用，每小时一次）

解决的缺口：以前只有「精读」是自动的（打标签触发），而**向量化和结构化抽取都要手动跑**，
导致用户在 Zotero 加了文献后，问答（查向量库）和对比表（查 structured）都看不到新文献。

做两件事，都是**增量**（已处理的跳过，没新文献时几秒结束）：
  1. 增量向量化   → `tools.ask.vectorize --light`（走 Zotero 全文API，本地 bge-m3，零成本）
  2. 增量粗层抽取 → `tools.extract --coarse`（本地 qwen，零成本；精层记录受保护不覆盖）

前提：Zotero 开着（取全文）+ Ollama 在跑（向量化/本地抽取）。两者都有保活任务。
用法: python -m host.autosync      （由任务计划 LiteratureAutoSync 每小时调用）
"""
import os
import sys
import time
from subprocess import TimeoutExpired

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters import embed as _embed
from shared.adapters import zotero_client as _zot
from shared.kernel import role
from shared.kernel.cli import flag
from shared.kernel.log import get_logger
from shared.kernel.paths import ROOT as _ROOT
from shared.kernel.subproc import run as _sub_run   # 子进程统一走积木：不弹窗+超时+UTF-8

# 日志名一直叫 auto_sync（模块搬过两次家了）：日志是**数据流**不是代码路径，
# 面板的日志下拉、诊断报告、B 机上已有的 auto_sync.log 都认这个名字。
log = get_logger('auto_sync')   # 统一日志：时间戳 + 落盘 + 自动轮转

# 两个依赖服务：探活函数在各自的适配层里（探活也是联网，红线 #5）
DEPS = (('ZoteroApp', 'Zotero', _zot.alive),
        ('OllamaService', 'Ollama', _embed.alive))


def _revive(task_name, disp, probe, wait=30):
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
        if probe():
            log(f'{disp} 已恢复')
            return True
    log(f'{disp} 拉起后仍未响应')
    return False


def check_deps():
    """检查依赖服务。拉不起来就跳过本轮（下轮再来），不报错刷屏。

    之前只「跳过」不拉起，结果 Zotero 开机没起来后就一直没人管，
    精读线静默停摆了 19 分钟用户才发现（踩坑 #33）。**保活任务就该负责保活。**
    """
    for task, disp, probe in DEPS:
        if probe() or _revive(task, disp, probe):
            continue
        log(f'跳过本轮：{disp} 未响应且拉起失败')
        return False
    return True


def _run_argv(argv, name, timeout=3600):
    """跑一条子进程命令，返回是否成功。所有输出只取最后一行当摘要。"""
    try:
        r = _sub_run(argv, timeout=timeout, cwd=_ROOT,
                     env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        tail = (r.stdout or '').strip().splitlines()
        log(f'{name}: {tail[-1] if tail else "(无输出)"}')
        return r.returncode == 0
    except TimeoutExpired:
        log(f'{name}: 超时（{timeout}s），下轮继续'); return False
    except Exception as e:
        log(f'{name}: 出错 {e}'); return False


def run_module(module, name, args=(), timeout=3600):
    """跑一个工具模块（`python -m tools.x.y`）。

    **按模块名拉起，不按文件路径** —— R2/R3 窗起工具是包不是散脚本，
    路径怎么变都不必再改这里；模块名是它们的对外契约，本来就该稳定。
    另外这样也不构成 `tools` import `tools`（子进程，不是 import 边）。
    """
    return _run_argv([sys.executable, '-m', module] + list(args), name, timeout)


def main():
    # 机器角色守卫：这件事只允许在运行端（主力机）做，见 docs/howto/两台机器的分工.md
    role.require_prod('定时增量同步', force=flag('--force'))
    log('=== 自动同步开始 ===')
    if not check_deps():
        return
    # 1. 增量向量化（新文献进向量库 → 问答能查到）
    run_module('tools.ask.vectorize', '增量向量化', ['--light'])
    # 2. 增量粗层结构化抽取（新文献进对比表 → 横向比较能看到）
    run_module('tools.extract', '增量粗层抽取', ['--coarse'])
    log('=== 自动同步结束 ===')


if __name__ == '__main__':
    main()
