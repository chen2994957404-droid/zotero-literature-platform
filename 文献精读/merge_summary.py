# -*- coding: utf-8 -*-
"""正文精读 + SI 精读合并的命令行入口 —— **合并逻辑已搬进 `pipelines/deepread/merge.py`**。

用法：
  python merge_summary.py <ZoteroKey>              # 合并并回写 Zotero
  python merge_summary.py <ZoteroKey> --no-upload  # 只生成不回写

这里只剩「合并之后要不要回写 Zotero」这一段 —— 回写是**界面/写回**的事，
不该长在编排环里（编排环只管产出文件，见 pipelines/deepread/__init__.py）。
"""
import os
import sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import paths
from shared.kernel.cli import pos, flag
from pipelines.deepread.merge import merge

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)     # 同文件夹脚本互相 import（upload_summaries 等）


def upload(key, out):
    """把合并版回写成 Zotero 的 summary 附件。"""
    try:
        from upload_summaries import do_one_file
        do_one_file(key, out, 'summary')
        return
    except ImportError:
        pass
    # upload_summaries 没有该函数则走通用逻辑：临时把合并版当作 summary 上传
    import upload_summaries as us
    orig = paths.summary(key)
    bak = orig + '.orig'
    os.replace(orig, bak)
    os.replace(out, orig)
    try:
        us.do_one(key)
    finally:
        os.replace(orig, out)
        os.replace(bak, orig)
    print('[已回写 Zotero] 附件 summary（合并版）')


def main():
    key = pos(0)
    if not key:
        print('用法: python merge_summary.py <ZoteroKey> [--no-upload]')
        sys.exit(1)
    out = merge(key)
    if out and out == paths.summary_full(key) and not flag('--no-upload'):
        upload(key, out)


if __name__ == '__main__':
    main()
