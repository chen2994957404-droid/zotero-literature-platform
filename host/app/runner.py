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

from shared.kernel import catalog, errors, paths, proc_lock, role
from shared.kernel.cli import flag
from shared.kernel.log import get_logger
from host.app import jobs

log = get_logger('app_jobs')


def try_fetch_si(pid, pdf_path, log=print):
    """精读前补一次 SI：有 DOI、目录里没记「确认没有 SI」、取全文用的浏览器开着才去取。

    取到 → 落进 data/raw/<id>/si.*；出版商说没挂 → 目录记 si_status=none，以后不再来。
    浏览器没开不算错：写一行日志，照常只精读正文。（同样从 host.watcher.service 搬来。）
    """
    doi = catalog.doi_of(catalog.read_meta(pid))
    if not doi:
        return False
    if catalog.si_status(pid) == catalog.SI_NONE:
        log('  [SI] 目录记着这篇没有补充材料（出版商页面确认过），不再去取')
        return False
    try:
        from tools import getpdf
        r = getpdf.land(doi, pdf_path=pdf_path)
    except Exception as e:                       # 浏览器没开 / 取件模块不可用 —— 不拖累精读
        log(f'  [SI] 这次没能补 SI：{str(e)[:100]}（照常只精读正文）')
        return False
    if r.get('si'):
        log(f'  [SI] 补到了补充材料：{os.path.basename(r["si"])}')
        return True
    log(f'  [SI] 没取到：{r.get("note") or "出版商那边没给"}')
    return False


def deepread_one(pid):
    """一篇精读 → (state, note)。"""
    from tools import deepread
    local = paths.local_pdf(pid)
    pdf_path = local if os.path.exists(local) else None
    si_exists = bool(paths.find_local_si(pid))
    if not si_exists and pdf_path:
        si_exists = try_fetch_si(pid, pdf_path, log=log)
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
