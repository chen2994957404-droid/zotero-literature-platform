# -*- coding: utf-8 -*-
"""prompts 自测：版本解析、最新版挑选、缺失报错、只读缓存。

**不碰真实提示词** —— 除最后一项（验证仓库里的提示词真的能读到）之外，
全部在临时目录里造假的 prompts/ 树。
用法: python shared/kernel/prompts/selftest.py
"""
import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import paths, prompts as P


def main():
    ok = 0
    total = 7

    # 1. spec 解析：带版本、不带版本、写错
    try:
        cases = (P.parse_spec('main@v2') == ('main', 2)
                 and P.parse_spec('si') == ('si', None))
        bad = False
        try:
            P.parse_spec('main@2')       # 少了 v
        except ValueError:
            bad = True
        if cases and bad:
            print('  [PASS] spec 解析（main@v2 / main / 写错的被拒）'); ok += 1
        else:
            print(f'  [FAIL] spec 解析异常: {P.parse_spec("main@v2")}')
    except Exception as e:
        print(f'  [FAIL] spec 解析抛异常: {e}')

    real_root = paths.ROOT
    tmp = tempfile.mkdtemp()
    try:
        d = os.path.join(tmp, 'tools', 'fake', 'prompts')
        os.makedirs(d)
        for fn, body in (('main_v1.txt', '第一版'), ('main_v2.txt', '第二版'),
                         ('si_v1.txt', 'SI 版'), ('readme.txt', '不是提示词'),
                         ('main_v10.txt', '第十版')):
            with open(os.path.join(d, fn), 'w', encoding='utf-8') as f:
                f.write(body)
        paths.ROOT = tmp

        # 2. 版本枚举：只认 <名>_v<数字>.txt，不认别的文件
        if P.versions('fake', 'main') == [1, 2, 10] and P.versions('fake', 'si') == [1]:
            print('  [PASS] 版本枚举正确（忽略非提示词文件）'); ok += 1
        else:
            print(f'  [FAIL] 版本枚举异常: {P.versions("fake", "main")}')

        # 3. 最新版按**数字**比大小，不是按字符串（v10 > v2，字符串比会反）
        if P.latest('fake', 'main') == 10 and P.load('fake', 'main') == '第十版':
            print('  [PASS] 最新版按数字比大小（v10 > v2）'); ok += 1
        else:
            print(f'  [FAIL] 最新版挑错了: v{P.latest("fake", "main")}')

        # 4. 钉死版本读到的就是那一版
        if P.load('fake', 'main@v1') == '第一版':
            print('  [PASS] 钉死版本读取'); ok += 1
        else:
            print('  [FAIL] 钉死版本读到了别的内容')

        # 5. listing 每个名字只列最新版（tool.toml 校验靠它）
        if P.listing('fake') == ['main@v10', 'si@v1']:
            print('  [PASS] listing 只列每个名字的最新版'); ok += 1
        else:
            print(f'  [FAIL] listing 异常: {P.listing("fake")}')

        # 6. 找不到要抛 MissingPrompt，且消息里得说清现有哪些 ——
        #    没有这句，用户只会看到一个光秃秃的「文件不存在」。
        try:
            P.load('fake', 'nothere@v1')
            print('  [FAIL] 缺失的提示词没有报错')
        except P.MissingPrompt as e:
            if 'main@v10' in str(e):
                print('  [PASS] 缺失报错且列出现有版本'); ok += 1
            else:
                print(f'  [FAIL] 报错了但没列出现有版本: {e}')
    finally:
        paths.ROOT = real_root
        P._CACHE.clear()          # 临时目录的内容不许留在缓存里污染真实读取
        shutil.rmtree(tmp, ignore_errors=True)

    # 7. 仓库里真实的提示词读得到（这一条防的是「搬完文件忘了改调用方」）
    got = P.listing('deepread')
    if 'main@v2' in got and len(P.load('deepread', 'main@v2')) > 500:
        print(f'  [PASS] 真实提示词可读：deepread {got}'); ok += 1
    else:
        print(f'  [FAIL] deepread 的提示词读不到: {got}')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
