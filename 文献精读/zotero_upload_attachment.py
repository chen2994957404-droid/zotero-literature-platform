# -*- coding: utf-8 -*-
"""上传附件到 Zotero 的命令行入口 —— **实现已收进 `adapters/zotero_client`**。

用法: python zotero_upload_attachment.py <父条目Key> <文件路径> <显示名>

搬家原因（阶段 3 下半，2026-08-27）：写 Zotero 的实现原来有三份，
各自拼 URL、各自拼鉴权头、各自处理版本冲突 —— 更要命的是
**机器角色守卫要在每一份里各写一遍，漏一处闸门就等于不存在**。
现在只有 `adapters/zotero_client/_web.py` 一处会碰 api.zotero.org。

新代码请直接调 `adapters.zotero_client.upload_attachment(...)`。
"""
import sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from adapters.zotero_client import upload_attachment      # noqa: F401 —— 供老代码继续 import
from core.cli import pos


def main():
    pk, fp, name = pos(0), pos(1), pos(2)
    if not (pk and fp and name):
        print(__doc__)
        sys.exit(1)
    print(f'上传 {fp} -> 条目 {pk}')
    print(f'完成，附件key={upload_attachment(pk, fp, name)}')


if __name__ == '__main__':
    main()
