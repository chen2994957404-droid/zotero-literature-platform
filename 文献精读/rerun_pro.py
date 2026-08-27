# -*- coding: utf-8 -*-
"""用 deepseek-v4-pro 重跑某篇已解析文献的正文精读（更准，适合重要文献）。

用法: python rerun_pro.py            列出可重跑的文献
      python rerun_pro.py <序号>     用 pro 重跑该篇

日常精读用 flash（输出长，省钱）；这里用 pro 重跑你想细品的那几篇。
**解析结果直接复用**（library/<key>/parsed/），不再消耗 MineRU 额度，
所以这一步只花一次 LLM 的钱。

2026-08-27 重写：原版读的是 `workflow_data/zotero_work` 和 `workflow_data/summary`,
这两个目录在现行数据契约下**根本不存在** —— 也就是说它已经死了很久，
一运行就抛 FileNotFoundError，而根目录的 .bat 还在正常地把用户引过来。
现在改为走 `core.paths` 与 `pipelines.deepread`，并且旧版自动备份成 .bak。
"""
import os
import shutil
import sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import json

from core import jobs, paths, role
from core.cli import flag, pos
from core.config import get_key
from pipelines import deepread
from pipelines.deepread import main_text

PRO_MODEL = 'deepseek-v4-pro'


def candidates():
    """能重跑的文献 = 解析结果还在的（不用再调 MineRU）。返回 [(key, 标题)]。"""
    out = []
    for key in paths.all_keys():
        if not os.path.exists(paths.layout(key)):
            continue
        title = key
        if os.path.exists(paths.meta(key)):
            try:
                title = json.load(open(paths.meta(key), encoding='utf-8')).get('title') or key
            except Exception:
                pass
        out.append((key, title))
    return out


def rerun(key, title=''):
    """用 pro 重跑正文精读。旧版先备份 —— **可还原是自主执行的前提**。"""
    out_html = paths.summary(key)
    if os.path.exists(out_html):
        bak = out_html + '.bak'
        shutil.copy2(out_html, bak)          # 每次都覆盖备份：留的是「上一版」
        print(f'  [备份] 旧版 → {os.path.basename(bak)}')
    print(f'用 {PRO_MODEL} 重跑：{title[:50]}')
    with jobs.track(key, deepread.STEP_MAIN, producer=main_text.PRODUCER,
                    model=PRO_MODEL, prompt_ver=main_text.PROMPT_VER):
        main_text.read_main(paths.parsed_dir(key), out_html, provider='deepseek',
                            model=PRO_MODEL, key=get_key('DEEPSEEK_KEY'))
    print(f'\n完成，结果已更新：{out_html}')
    print('（想看旧版：同目录下的 summary.html.bak）')


def main():
    rows = candidates()
    idx_raw = pos(0)
    if not idx_raw:
        print('=== 可用 pro 重跑的已解析文献 ===\n')
        for i, (key, title) in enumerate(rows, 1):
            print(f'  [{i}] {title[:55]}')
        if not rows:
            print('  （没有已解析的文献 —— 先让 watcher 精读一篇）')
        print('\n用法：python rerun_pro.py <序号>   例如 python rerun_pro.py 2')
        return

    # 机器角色守卫：调用付费 API，只允许在运行端/测试端做
    role.require_prod('用 pro 重跑精读（调用付费 API）', force=flag('--force'))
    try:
        idx = int(idx_raw) - 1
    except ValueError:
        print('序号要是数字'); sys.exit(1)
    if not 0 <= idx < len(rows):
        print('序号超范围'); sys.exit(1)
    rerun(*rows[idx])


if __name__ == '__main__':
    main()
