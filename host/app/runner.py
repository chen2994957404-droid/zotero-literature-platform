# -*- coding: utf-8 -*-
"""host.app.runner · 跑文献库应用的作业队列：一篇一篇来，队列空了就退出。

由应用后台在有人点「精读」时拉起（`jobs.ensure_runner`），不是常驻服务。
同一时刻只许一个（proc_lock），所以不会两篇同时花钱。

单篇精读（2026-10-12 用户定：不回写 Zotero、只做单篇）：
    有公众号范文 → 范文当正文精读，只补 SI（同打标签精读）
    只有正文 → 先试着取一次 SI
    → tools.deepread.run（正文 / SI / 合并；每天的花费上限在 shared.kernel.budget 兜着）
产物落在证据库那篇的目录里，应用详情页直接出现「正文精读」等按钮。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.kernel import errors, paths, proc_lock, role
from shared.kernel.cli import flag
from shared.kernel.log import get_logger
from host.app import jobs

log = get_logger('app_jobs')


def deepread_one(pid):
    """一篇精读 → (state, note)。"""
    from host.watcher.service import _try_fetch_si, adopt_reference
    from tools import deepread
    if adopt_reference(pid, log=log):
        log('  公众号范文装上当正文精读，只补 SI')
    local = paths.local_pdf(pid)
    pdf_path = local if os.path.exists(local) else None
    si_exists = bool(paths.find_local_si(pid))
    if not si_exists and pdf_path:
        si_exists = _try_fetch_si(pid, {'data': {}}, pdf_path)
    r = deepread.run(pid, pdf_path=pdf_path, si_exists=si_exists, log=log)
    names = {'full': '全文精读完成', 'main': '正文精读完成', 'si': 'SI 精读完成',
             'nopdf': '本地没有可精读的文件', 'failed': '没做成：' + str(r.error or '')[:200]}
    return ('done' if r.state in ('full', 'main', 'si') else 'failed'), names.get(r.state, r.state)


def main():
    role.require_prod('跑文献库应用里点的精读（调用大模型，要花钱）', force=flag('--force'))
    if not proc_lock.single_instance(jobs.RUNNER_LOCK):
        return 0                                   # 已有一个在跑，它会把新排的也做掉
    while True:
        job = jobs.next_queued()
        if not job:
            return 0
        jobs.mark(job['id'], 'running')
        log(f"[开始] {job['kind']} {job['pid']}")
        try:
            if job['kind'] == 'deepread':
                state, note = deepread_one(job['pid'])
            else:
                state, note = 'failed', f"不认识的作业：{job['kind']}"
        except Exception as e:
            state, note = 'failed', f'{type(e).__name__}: {str(e)[:200]}'
        jobs.mark(job['id'], state, note)
        log(f"[结束] {job['pid']} {state} {note}")


if __name__ == '__main__':
    try:
        sys.exit(main())
    except errors.WrongMachineError as e:
        print(e)
        sys.exit(1)
