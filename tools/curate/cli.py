# -*- coding: utf-8 -*-
"""库房维护的命令行入口（只分发，逻辑在各子模块）。

用法:
    python -m tools.curate sync                     定时增量同步（任务计划每小时跑的就是这条）
    python -m tools.curate junk                     列出无正文 PDF 的垃圾条目（**只列，不删**）
    python -m tools.curate junk --删除              按上一步的清单删（危险，先看清单）
    python -m tools.curate junk --删除 --只删A      只删确认是重复残留的那组
    python -m tools.curate rename <全库json路径>     附件改名，不带 apply = 只预览
    python -m tools.curate rename <全库json> apply   真改
    python -m tools.curate backfill                 给缺 meta.json 的补元数据
    python -m tools.curate tags                     标签改嵌套写法（不带 apply = 预览）
    python -m tools.curate tags apply               真改

⚠ 除 junk 列清单、rename/tags 的预览之外，其余都会**写回 Zotero**，
   只允许在主力机上跑（role.require_prod 会拦住编程端）。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel.cli import pos, wants_help

ACTIONS = ('sync', 'junk', 'rename', 'backfill', 'tags')


def main():
    if wants_help():
        print(__doc__)
        return 0
    action = (pos(0) or '').lower()
    if action not in ACTIONS:
        print(__doc__)
        return 2

    # 分发前把动作词从 argv 里摘掉：各子模块的 main() 自己用 pos(0)
    # 取真正的参数（rename 的 json 路径、tags 的 apply）。不摘掉的话，
    # 「rename 某.json」会被 rename.main() 当成「路径是 rename」。
    sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != action]

    import importlib
    mod = importlib.import_module(f'tools.curate.{action}')
    mod.main()
    return 0


if __name__ == '__main__':
    sys.exit(main())
