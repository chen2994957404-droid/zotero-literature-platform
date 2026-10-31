# -*- coding: utf-8 -*-
"""host.mcp.fulltext_job · 取全文后台作业 = 取全文（tools.getpdf）+ 收尾补作者索引（tools.library）。

用法（由 `science._fulltext` spawn，参数与 `python -m tools.getpdf` 完全一样）：
    python -m host.mcp.fulltext_job <DOI...> --fulltext --limit N

**为什么要这一层**（2026-10-31）：文献库应用加了「导入」后，新收的文献卡片上没有作者和摘要 ——
那份索引（`tools.library.oaindex`）原来只能整库重建。补它要 library，取全文是 getpdf，
工具之间不许互相 import（硬规则 2），跨工具串起来是 host 的事，所以放这里。
Claude Science 交的 `paper_fulltext` 也走这条，它收进来的文献一样补上。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

import io
import json

from shared.kernel import paths
from shared.kernel.log import get_logger

log = get_logger('fulltext_job')


def landed_ids(progress_path):
    """进度文件里这次收进库的文献 id（取到正文的）。"""
    try:
        d = json.load(io.open(progress_path, encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return [r['id'] for r in d.get('results') or [] if r.get('id') and os.path.exists(paths.local_pdf(r['id']))]


def fill_index(pids):
    """新文献补作者 + 摘要，再按研究团队名单重挂（本地，零网络）。失败只记日志：不影响已经收进库的文献。"""
    if not pids:
        return 0
    from tools.library import oaindex, teams
    try:
        n = oaindex.add(pids)
        if n:
            teams.build()
        log.info(f'作者索引补了 {n}/{len(pids)} 篇')
        return n
    except Exception as e:
        log.info(f'作者索引没补上（不影响收进库的文献，以后「检索 --建索引」会补）：{type(e).__name__}: {e}')
        return 0


def main():
    from tools.getpdf.cli import main as getpdf_main
    code = getpdf_main()
    fill_index(landed_ids(paths.runtime('fulltext_progress.json')))
    return code


if __name__ == '__main__':
    sys.exit(main())
