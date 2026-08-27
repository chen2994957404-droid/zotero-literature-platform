# -*- coding: utf-8 -*-
"""proc_lock 自测：验证「同时只有一份」这个承诺真的成立。
用法: python modules/proc_lock/selftest.py
"""
import sys, os, io

# 可能被无控制台的 pythonw 拉起，强制 UTF-8 输出，避免打印中文时崩（踩坑 #32）
# 用 reconfigure 而非替换 sys.stdout：后者会让原对象被回收、底层缓冲被关闭，
# 表现为程序跑到一半 print 抛「I/O operation on closed file」（踩坑 #37）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from modules.proc_lock import single_instance, release, holder, _lock_path
from modules.subproc import run as _run

NAME = '_selftest_lock'


def main():
    ok = 0
    total = 4

    release(NAME)
    if os.path.exists(_lock_path(NAME)):
        os.remove(_lock_path(NAME))

    # 1. 首次抢锁应成功
    if single_instance(NAME):
        print('  [PASS] 首次抢锁成功'); ok += 1
    else:
        print('  [FAIL] 首次就抢不到锁')

    # 2. 同一进程重复抢应仍为 True（幂等，不能自己把自己挡在外面）
    if single_instance(NAME):
        print('  [PASS] 同进程重复抢锁幂等'); ok += 1
    else:
        print('  [FAIL] 同进程再抢被拒，说明会自锁')

    # 3. 另一个进程抢同一把锁应失败 —— 这是本积木存在的唯一理由
    # 子进程直接 import：项目已装成包（pip install -e .），不需要塞 sys.path
    code = (f"from modules.proc_lock import single_instance;"
            f"print('GOT' if single_instance('{NAME}') else 'BLOCKED')")
    r = _run([sys.executable, '-c', code], timeout=40)
    if 'BLOCKED' in r.stdout:
        print('  [PASS] 第二个进程被挡住（核心承诺成立）'); ok += 1
    else:
        print(f'  [FAIL] 第二个进程也拿到了锁: {r.stdout.strip()} {r.stderr[-150:]}')

    # 4. 僵尸锁（持有者已死）应能被自动接管，否则一次崩溃就永久起不来
    release(NAME)
    with open(_lock_path(NAME), 'w', encoding='utf-8') as f:
        f.write('999999')          # 几乎不可能存在的 PID
    if holder(NAME) is None and single_instance(NAME):
        print('  [PASS] 僵尸锁被自动接管'); ok += 1
    else:
        print('  [FAIL] 僵尸锁没被接管，服务将永远起不来')

    release(NAME)
    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
