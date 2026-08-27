# -*- coding: utf-8 -*-
"""subproc 自测：验证「安静、带超时、编码正确」三项承诺。
用法: python modules/subproc/selftest.py
"""
import sys, os, subprocess, time, io

# 自测自己也可能被无控制台的 pythonw 拉起，此时 stdout 是 GBK，打印中文会崩。
# 强制把自己的输出改成 UTF-8 —— 测试工具不该因为环境不同而假报错。
# 用 reconfigure 而非替换 sys.stdout：后者会让原对象被回收、底层缓冲被关闭，
# 表现为程序跑到一半 print 抛「I/O operation on closed file」（踩坑 #37）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from modules.subproc import run, out, powershell, _NO_WINDOW


def main():
    ok = 0
    total = 5

    # 1. 基本执行与输出
    r = run([sys.executable, '-c', 'print("hello")'])
    if r.returncode == 0 and 'hello' in r.stdout:
        print('  [PASS] 基本执行拿到输出'); ok += 1
    else:
        print(f'  [FAIL] 基本执行异常: {r.returncode} {r.stdout!r}')

    # 2. 中文输出不乱码不炸 —— 项目里到处是中文日志
    r = run([sys.executable, '-c', 'print("中文输出正常")'])
    if '中文输出正常' in (r.stdout or ''):
        print('  [PASS] 中文输出正确解码'); ok += 1
    else:
        print(f'  [FAIL] 中文输出异常: {r.stdout!r}')

    # 3. 超时能生效（不会永远挂住）
    t0 = time.time()
    try:
        run([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=3)
        print('  [FAIL] 超时没生效')
    except subprocess.TimeoutExpired:
        if time.time() - t0 < 15:
            print('  [PASS] 超时按时触发'); ok += 1
        else:
            print('  [FAIL] 超时触发太晚')

    # 4. out() 在命令失败时返回默认值而不抛异常
    if out(['__这个命令不存在__'], default='兜底') == '兜底':
        print('  [PASS] out() 失败时安静兜底'); ok += 1
    else:
        print('  [FAIL] out() 没有正确兜底')

    # 5. Windows 上必须带「不弹窗」标志 —— 这是本积木存在的首要理由
    if os.name == 'nt':
        if _NO_WINDOW != 0:
            print('  [PASS] 已启用不弹窗标志'); ok += 1
        else:
            print('  [FAIL] 不弹窗标志为 0，窗口还会弹')
    else:
        print('  [PASS] 非 Windows，无需窗口标志'); ok += 1

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
