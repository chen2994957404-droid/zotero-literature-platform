# -*- coding: utf-8 -*-
"""python -m host.daily —— 跑一次每日作业（盯新刊 + 补摘要 + 升 1 级取件）。"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.kernel import role
from shared.kernel.cli import flag, wants_help
from host import daily


def main():
    if wants_help():
        print(__doc__)
        return 0
    # 借浏览器向出版商取件、写 data/raw —— 编程端默认拦住（测试角色放行）
    role.require_prod('每日作业：盯新刊 + 自动升 1 级取件', force=flag('--force'))
    from shared.kernel.proc_lock import single_instance, holder
    if not single_instance('daily'):
        daily.log(f'已有一份每日作业在跑（PID={holder("daily")}），本次退出')
        return 0
    daily.log('每日作业启动')
    try:
        daily.run()
    except Exception as e:
        daily.log(f'[每日作业失败] {type(e).__name__}: {e}')
        return 1
    return 0


if __name__ == '__main__':
    from shared.kernel import errors as _err
    try:
        sys.exit(main())
    except _err.WrongMachineError as _e:
        print(str(_e))
        sys.exit(2)
