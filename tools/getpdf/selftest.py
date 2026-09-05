# -*- coding: utf-8 -*-
"""getpdf 自测：纯离线，不碰浏览器、不碰网络。

**这个工具的主体在别人家的浏览器里跑**，本机验不了。所以这里只验
「不联网也必须成立」的那部分：文件名安全、落盘位置走 paths、
已有文件会跳过、撞验证码会停而不是接着跑。

浏览器那半只能在真机上验：`python -m tools.getpdf --probe`。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import io
import tempfile

from shared.kernel import paths
from tools import getpdf


def main():
    ok = total = 0

    total += 1
    n = getpdf.safe_name('10.1016/j.cej.2025.164092')
    if '/' not in n and n.startswith('10.1016') and n.endswith('164092'):
        print(f'  [PASS] DOI → 文件名：{n}'); ok += 1
    else:
        print(f'  [FAIL] 文件名不对：{n}')

    total += 1
    # 红线 #4：路径必须从 paths 来，不许自己拼 data
    d = getpdf.out_dir()
    if d.startswith(paths.INCOMING):
        print('  [PASS] 落盘位置走 paths.INCOMING'); ok += 1
    else:
        print(f'  [FAIL] 落盘位置没走 paths：{d}')

    total += 1
    # 盘上已经有了就跳过 —— 重跑一批不该重敲出版商
    with tempfile.TemporaryDirectory() as tmp:
        doi = '10.1016/fake.test.1'
        p = os.path.join(tmp, getpdf.safe_name(doi) + '.pdf')
        with io.open(p, 'wb') as fh:
            fh.write(b'%PDF-1.7' + b'x' * 4096)
        r = getpdf.fetch_one(doi, tmp)
        if r['ok'] and r['reason'] == 'exists' and r['path'] == p:
            print('  [PASS] 盘上已有的会跳过，不重下'); ok += 1
        else:
            print(f'  [FAIL] 已有文件没跳过：{r}')

    total += 1
    # 撞上验证码要停整批 —— 硬跑只会把剩下的全废掉，还多敲出版商一堆次
    src = io.open(os.path.join(os.path.dirname(__file__), '__init__.py'),
                  encoding='utf-8').read()
    if "if r['reason'] == 'captcha':" in src and 'break' in src:
        print('  [PASS] 撞验证码是「停」不是「跳过」'); ok += 1
    else:
        print('  [FAIL] 找不到撞验证码就停的逻辑')

    total += 1
    if getpdf.GAP >= 10 and getpdf.LIMIT <= 50:
        print(f'  [PASS] 默认值保守：间隔 {getpdf.GAP} 秒、单次上限 {getpdf.LIMIT} 篇'); ok += 1
    else:
        print(f'  [FAIL] 默认值太激进：GAP={getpdf.GAP} LIMIT={getpdf.LIMIT}')

    total += 1
    c = getpdf.summarize([{'reason': 'ok'}, {'reason': 'ok'}, {'reason': 'no_access'}])
    if c == {'ok': 2, 'no_access': 1}:
        print('  [PASS] 结果汇总'); ok += 1
    else:
        print(f'  [FAIL] 汇总不对：{c}')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
