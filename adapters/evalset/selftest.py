# -*- coding: utf-8 -*-
"""evalset 自测：验证评价记录、快照计算与统计。

**不碰真实评测集** —— 测试用临时文件，跑完还原。
测试污染用户数据是不可接受的。
用法: python adapters/evalset/selftest.py
"""
import sys, os, json, tempfile

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import adapters.evalset as E


def main():
    ok = 0
    total = 6

    real = E.EVALSET
    tmpdir = tempfile.mkdtemp()
    E.EVALSET = os.path.join(tmpdir, 'evalset.json')   # 隔离，不碰真实数据
    try:
        # 1. 空评测集不炸
        if E.load() == {} and E.get('X') is None:
            print('  [PASS] 空评测集安全'); ok += 1
        else:
            print('  [FAIL] 空评测集处理异常')

        # 2. 存取往返
        E.save('KEY1', 'good', title='测试文献一')
        r = E.get('KEY1')
        if r and r['verdict'] == 'good' and r['title'] == '测试文献一':
            print('  [PASS] 评价存取往返'); ok += 1
        else:
            print(f'  [FAIL] 存取异常: {r}')

        # 3. 非法评分被拒（不能悄悄存进一个无意义的值）
        try:
            E.save('KEY2', 'maybe')
            print('  [FAIL] 非法 verdict 未被拦下')
        except ValueError:
            print('  [PASS] 非法评分被拒'); ok += 1

        # 4. pending 只列没评过的
        E.save('KEY3', 'bad', reasons=['too_vague'])
        p = E.pending(['KEY1', 'KEY3', 'KEY9'])
        if p == ['KEY9']:
            print('  [PASS] pending 正确排除已评价的'); ok += 1
        else:
            print(f'  [FAIL] pending 结果异常: {p}')

        # 5. 统计与「样本够不够」判断
        s = E.stats()
        if s['total'] == 2 and s['good'] == 0 and s['bad'] == 0 and not s['ready']:
            # 快照为 None（这些 key 没有真实精读文件），所以 good/bad 计数为 0
            print('  [PASS] 统计正确（无快照的不计入对比）'); ok += 1
        else:
            print(f'  [FAIL] 统计异常: {s}')

        # 6. 快照：拿库里真实存在的一篇算，验证指标能算出来
        import glob
        real_keys = [os.path.basename(os.path.dirname(f))
                     for f in glob.glob(os.path.join(E.LIBRARY, '*', 'summary.html'))]
        if real_keys:
            snap = E.snapshot(real_keys[0])
            # 合理性检查：数值数不可能超过字数的 1/5。
            # 曾因为没剔除 base64 内嵌图，把 6641 字的精读算出 13471 处数值。
            # **一个错得离谱的指标比没有指标更糟** —— 它会安静地污染将来的校准。
            sane = snap and snap['chars'] > 0 and snap['numbers'] <= snap['chars'] / 5
            if sane:
                print(f"  [PASS] 快照可算且数值合理：{snap['chars']} 字 / "
                      f"{snap['figures']} 图 / {snap['numbers']} 处数值 / "
                      f"{snap['sections']} 个章节"); ok += 1
            else:
                print(f'  [FAIL] 快照异常或数值失真: {snap}')
        else:
            print('  [SKIP] 库里没有精读文件'); ok += 1

        if E.snapshot('NOT_EXIST_KEY') is not None:
            print('  [note] 不存在的 key 应返回 None')
    finally:
        E.EVALSET = real
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
